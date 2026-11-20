# tests for controller/s2k_transfers.py and core/s2k_client.py: sample audio over an s2k-send server (SCSI) instead of MIDI.
# A fake client stands in for the server; the real SamplerController delegates to the engine.

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc
import io
import json
import threading
import urllib.error

import pytest
from PySide6.QtCore import QObject, Signal

from controller import s2k_transfers
from controller.sampler_controller import SamplerController
from core import s2k_client, sampler_models, sds_encoder

from test_s950_transfers import qapp, wait_until  # noqa: F401


class _Midi(QObject):
    sysex_received = Signal(bytes)

    def __init__(self):
        super().__init__()
        self.input_name = "Fake In"
        self.output_name = "Fake Out"
        self.sent = []

    def send_sysex(self, data):
        self.sent.append(list(data))


class FakeClient:
    """The s2k-send server's job API, done at once. `fail_with` makes the job end failed; `hold` keeps start() waiting."""

    def __init__(self):
        self.jobs = {}
        self.uploads = {}
        self.cancelled = []
        self.started = []
        self.fail_with = None
        self.hold = None
        self.audio = {}
        self.headers = {}

    busy_left = 0
    fail_code = "send_failed"
    bus_state = "idle"
    pairs = ()

    def status(self):
        return {"server": "s2kserver", "version": "test", "bus": {"state": self.bus_state}}

    def create_job(self, specs, verify=True, block=16384):
        if self.busy_left:
            self.busy_left -= 1
            raise s2k_client.S2kError(409, "busy", "bus in use")
        for i, spec in enumerate(specs):
            if not s2k_client.MIN_RATE <= spec["rate"] <= s2k_client.MAX_RATE:
                raise s2k_client.S2kError(400, "bad_rate", f"sample {i}: rate out of range")
        job_id = f"job{len(self.jobs)}"
        self.jobs[job_id] = {"id": job_id, "state": "awaiting_audio", "samples": specs}
        self.uploads[job_id] = {}
        return dict(self.jobs[job_id])

    def upload(self, job_id, index, pcm):
        self.uploads[job_id][index] = pcm
        if len(self.uploads[job_id]) == len(self.jobs[job_id]["samples"]):
            self.jobs[job_id]["state"] = "ready"
        return dict(self.jobs[job_id])

    def start(self, job_id):
        self.started.append(job_id)
        if self.hold is not None:
            self.hold.wait(5)
        job = self.jobs[job_id]
        names = [s["name"] for s in job["samples"]]
        if self.fail_with is not None:
            job["state"] = "failed"
            job["error"] = {"code": self.fail_code, "message": self.fail_with, "done": [{"name": names[0], "slot": 5}]}
        else:
            job["state"] = "done"
            job["result"] = {
                "samples": [{"name": n, "slot": 5 + i} for i, n in enumerate(names)],
                "overall_kbps": 66.5,
                "pairs": list(self.pairs),
            }
        job["progress"] = {"phase": "verify_audio", "sample_index": len(names) - 1, "done": 10, "total": 10}
        return dict(job)

    def job(self, job_id, since=0):
        return {**self.jobs[job_id], "log": [{"n": 0, "msg": "hello"}], "next": 1}

    def cancel(self, job_id):
        self.cancelled.append(job_id)
        self.jobs[job_id]["state"] = "cancelled"
        return dict(self.jobs[job_id])

    download_state = None  # e.g. "queued": a download job never gets further

    def start_download(self, slot):
        job_id = f"job{len(self.jobs)}"
        job = {"id": job_id, "kind": "download", "slot": slot, "state": self.download_state or "done"}
        if self.download_state is None:
            if slot in self.audio:
                frames = len(self.audio[slot][1])
                job["progress"] = {"phase": "download", "done": 2 * frames, "total": 2 * frames}
                job["result"] = {"slot": slot, "frames": frames}
            else:
                job["state"] = "failed"
                job["error"] = {"code": "not_found", "message": f"no sample in slot {slot}"}
        self.jobs[job_id] = job
        return {**job, "state": "queued"}

    def download_audio(self, job_id):
        slot = self.jobs[job_id]["slot"]
        rate, samples = self.audio[slot]
        return {"name": f"S{slot}", "rate": rate, "frames": len(samples), "root": 60}, s2k_client.pcm_from_samples(samples)

    def sample(self, slot):
        return {"slot": slot, "header_hex": self.headers.get(slot, "")}


@pytest.fixture
def rig(qapp, monkeypatch):  # noqa: F811
    monkeypatch.setenv(s2k_transfers.ENV_VAR, "http://pi.test:8420")
    controller = SamplerController(_Midi())
    controller.sampler_model = sampler_models.AKAI_S2000_S3000
    client = FakeClient()
    controller._s2k_engine = s2k_transfers.S2kTransfers(controller, "http://pi.test:8420", client=client)
    monkeypatch.setattr(controller, "refresh_sample_list", lambda silent=False: None)
    monkeypatch.setattr(s2k_transfers, "_JOB_POLL_S", 0.0)
    monkeypatch.setattr(s2k_transfers, "_BUSY_WAIT_S", 0.0)
    rec = {"finished": [], "files": [], "status": [], "received": [], "rx_finished": [], "unit": [], "rx_progress": []}
    controller.transfer_finished.connect(rec["finished"].append)
    controller.file_transferred.connect(rec["files"].append)
    controller.status_changed.connect(rec["status"].append)
    controller.sample_received.connect(rec["received"].append)
    controller.receive_finished.connect(rec["rx_finished"].append)
    controller.unit_progress.connect(rec["unit"].append)
    controller.receive_progress.connect(lambda done, total: rec["rx_progress"].append((done, total)))
    yield controller, client, rec
    if client.hold is not None:
        client.hold.set()
    worker = controller._s2k_engine._worker
    if worker is not None:
        worker.join(5)
    gc.collect()  # here, not on a later test's worker thread, where freeing Qt objects crashes


def _wav(tmp_path, name, rate=44100, frames=100, stereo=False):
    path = str(tmp_path / name)
    left = [(i * 37) % 2000 - 1000 for i in range(frames)]
    if stereo:
        sds_encoder.write_wav_file_stereo(path, left, [-s for s in left], rate, 16)
    else:
        sds_encoder.write_wav_file(path, left, rate, 16)
    return path


def _entry(path, **kw):
    return {"filepath": path, "name": None, "bit_depth": 16, "sample_rate": None, "mono": False, **kw}


@pytest.mark.parametrize(
    "value, expected",
    [("", None), ("off", None), ("0", None), ("1", s2k_transfers.DEFAULT_SERVER_URL), ("http://x:1", "http://x:1")],
)
def test_server_url_comes_from_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv(s2k_transfers.ENV_VAR, value)
    assert s2k_transfers.server_url() == expected


def test_names_and_rates_are_what_the_server_accepts():
    assert s2k_client.akai_name("kick_drum (1)!") == "KICK DRUM  1"
    assert s2k_client.akai_name("___") == "SAMPLE"


def test_pcm_round_trips():
    samples = [0, 1, -1, 32767, -32768, 1234]
    assert s2k_client.samples_from_pcm(s2k_client.pcm_from_samples(samples)) == samples


def test_plan_splits_stereo_keeps_rates_and_names_unique(tmp_path):
    stereo = _wav(tmp_path, "loop.wav", stereo=True)
    low = _wav(tmp_path, "kick.wav", rate=11025, frames=50)
    again = _wav(tmp_path, "KICK.wav")
    units, skipped = s2k_transfers.plan_units(
        [_entry(stereo), _entry(low), _entry(again), _entry(str(tmp_path / "missing.wav"))]
    )
    assert [u["name"] for u in units] == ["LOOP-L", "LOOP-R", "KICK", "KICK2"]
    assert [u["file"] for u in units] == [0, 0, 1, 2]
    assert units[2]["rate"] == 11025 and len(units[2]["samples"]) == 50  # never resampled for the server
    assert [path for path, _ in skipped] == [str(tmp_path / "missing.wav")]


def test_a_batch_goes_as_one_job_and_reports_every_file(rig, tmp_path):
    controller, client, rec = rig
    a, b = _wav(tmp_path, "a.wav"), _wav(tmp_path, "b.wav", stereo=True)
    assert controller.send_file_queue([_entry(a), _entry(b)]) is True
    assert wait_until(lambda: rec["finished"])
    assert rec["finished"] == [True]
    assert rec["files"] == [a, b]
    assert [s["name"] for s in client.jobs["job0"]["samples"]] == ["A", "B-L", "B-R"]
    assert len(client.uploads["job0"][0]) == 200
    assert not controller.midi_manager.sent
    assert not controller.is_transfer_busy()


def test_a_failed_job_reports_only_the_files_that_arrived(rig, tmp_path):
    controller, client, rec = rig
    client.fail_with = "bus error"
    a, b = _wav(tmp_path, "a.wav"), _wav(tmp_path, "b.wav")
    controller.send_file_queue([_entry(a), _entry(b)])
    assert wait_until(lambda: rec["finished"])
    assert rec["finished"] == [False]
    assert rec["files"] == [a]
    assert "bus error" in rec["status"][-1]


@pytest.mark.parametrize(
    "code, bus, expected",
    [
        ("list_mismatch", "needs_attention", "sample list isn't what was expected"),
        ("verify_failed", "idle", "didn't read back the same"),
        ("send_failed", "needs_attention", "power-cycle the S2000 and the Pi"),
        ("send_failed", "idle", "bus error"),
        ("verify_failed", "needs_attention", "power-cycle the S2000 and the Pi"),
    ],
)
def test_a_failed_job_says_what_to_do_next(rig, tmp_path, code, bus, expected):
    controller, client, rec = rig
    client.fail_with, client.fail_code, client.bus_state = "bus error", code, bus
    controller.send_file_queue([_entry(_wav(tmp_path, "a.wav"))])
    assert wait_until(lambda: rec["finished"])
    assert rec["finished"] == [False]
    assert expected in rec["status"][-1]


def test_a_failed_job_logs_how_to_fetch_its_evidence(rig, tmp_path, monkeypatch):
    controller, client, rec = rig
    lines = []
    monkeypatch.setattr(s2k_transfers._log(), "warning", lines.append)
    client.fail_with = "bus error"
    controller.send_file_queue([_entry(_wav(tmp_path, "a.wav"))])
    assert wait_until(lambda: rec["finished"])
    assert any("--fetch-job job0" in line for line in lines)


def test_a_stereo_pair_the_s2000_did_not_link_is_a_warning(rig, tmp_path, monkeypatch):
    controller, client, rec = rig
    lines = []
    monkeypatch.setattr(s2k_transfers._log(), "warning", lines.append)
    client.pairs = [{"left": "LOOP-L", "right": "LOOP-R", "linked": False, "left_partner": None, "right_partner": None}]
    controller.send_file_queue([_entry(_wav(tmp_path, "loop.wav", stereo=True))])
    assert wait_until(lambda: rec["finished"])
    assert rec["finished"] == [True]
    assert any("NOT linked" in line for line in lines)


def test_cancel_before_the_job_starts_cancels_it_on_the_server(rig, tmp_path, monkeypatch):
    controller, client, rec = rig
    gate = threading.Event()
    real_create = client.create_job

    def slow_create(*args, **kw):
        gate.wait(5)
        return real_create(*args, **kw)

    monkeypatch.setattr(client, "create_job", slow_create)
    controller.send_file_queue([_entry(_wav(tmp_path, "a.wav"))])
    controller.cancel_transfer()
    gate.set()
    assert rec["finished"] == [False]
    assert wait_until(lambda: client.cancelled == ["job0"])
    assert not client.started


def test_a_running_job_is_not_cancelled(rig, tmp_path):
    controller, client, rec = rig
    client.hold = threading.Event()
    controller.send_file_queue([_entry(_wav(tmp_path, "a.wav"))])
    assert wait_until(lambda: client.started)
    controller.cancel_transfer()
    assert "can't be stopped" in rec["status"][-1]
    assert controller.is_transfer_busy()
    client.hold.set()
    assert wait_until(lambda: rec["finished"])
    assert rec["finished"] == [True]


def test_receive_saves_each_sample_as_a_wav(rig, tmp_path):
    controller, client, rec = rig
    client.audio = {3: (22050, [1, 2, 3, -4]), 4: (44100, [5, 6])}
    paths = [str(tmp_path / "three.wav"), str(tmp_path / "four.wav")]
    controller.receive_samples([(3, paths[0]), (4, paths[1])])
    assert wait_until(lambda: rec["rx_finished"])
    assert rec["rx_finished"] == [True]
    assert rec["received"] == paths
    assert sds_encoder.read_wav_channels(paths[0]) == ([[1, 2, 3, -4]], 22050)
    assert not controller.midi_manager.sent
    assert (4, 4) in rec["rx_progress"]
    assert any("Receiving sample 3 over SCSI (1/2): 100%" in s for s in rec["status"])


def test_an_empty_slot_fails_the_receive(rig, tmp_path):
    controller, client, rec = rig
    controller.receive_samples([(9, str(tmp_path / "x.wav"))])
    assert wait_until(lambda: rec["rx_finished"])
    assert rec["rx_finished"] == [False]
    assert rec["status"][-1] == "There is no sample in slot 9 on the S2000"


def test_cancelling_a_receive_cancels_its_queued_download_job(rig, tmp_path):
    controller, client, rec = rig
    client.download_state = "queued"
    controller.receive_samples([(0, str(tmp_path / "x.wav"))])
    assert wait_until(lambda: client.jobs)
    controller.cancel_transfer()
    assert rec["rx_finished"] == [False]
    assert wait_until(lambda: client.cancelled == ["job0"])
    assert not rec["received"]


def test_an_unreachable_server_fails_the_receive(rig, tmp_path, monkeypatch):
    controller, client, rec = rig

    def unreachable(slot):
        raise s2k_client.S2kError(0, "unreachable", "nope")

    monkeypatch.setattr(client, "start_download", unreachable)
    controller.receive_samples([(0, str(tmp_path / "x.wav"))])
    assert wait_until(lambda: rec["rx_finished"])
    assert rec["rx_finished"] == [False]
    assert "Couldn't reach the S2K server" in rec["status"][-1]


@pytest.mark.parametrize("model", [sampler_models.AKAI_S1000, sampler_models.GENERIC_SDS])
def test_other_models_stay_on_midi(qapp, monkeypatch, model):  # noqa: F811
    monkeypatch.setenv(s2k_transfers.ENV_VAR, "1")
    controller = SamplerController(_Midi())
    controller.set_device_type(model)
    assert controller._s2k is None


def test_without_the_switch_transfers_stay_on_midi(qapp, monkeypatch):  # noqa: F811
    monkeypatch.delenv(s2k_transfers.ENV_VAR, raising=False)
    controller = SamplerController(_Midi())
    controller.sampler_model = sampler_models.AKAI_S2000_S3000
    assert controller._s2k is None


def test_the_client_turns_an_error_reply_into_s2k_error():
    def opener(request, timeout):
        body = json.dumps({"error": {"code": "busy", "message": "bus in use"}}).encode()
        raise urllib.error.HTTPError(request.full_url, 409, "Conflict", {}, io.BytesIO(body))

    with pytest.raises(s2k_client.S2kError) as caught:
        s2k_client.S2kClient("http://pi.test:8420", opener=opener).samples()
    assert (caught.value.status, caught.value.code) == (409, "busy")


@pytest.mark.parametrize(
    "typed, url",
    [
        ("piscsi.local", "http://piscsi.local:8420"),
        ("http://10.0.0.5:9000/", "http://10.0.0.5:9000"),
        ("10.0.0.5", "http://10.0.0.5:8420"),
        ("", s2k_client.DEFAULT_URL),
    ],
)
def test_a_typed_server_address_becomes_a_url(typed, url):
    assert s2k_client.normalize_url(typed) == url


def test_the_settings_choice_is_used_unless_the_environment_overrides_it(monkeypatch):
    monkeypatch.delenv(s2k_transfers.ENV_VAR, raising=False)
    assert s2k_transfers.server_url(None) is None
    assert s2k_transfers.server_url("pi.local") == "http://pi.local:8420"
    monkeypatch.setenv(s2k_transfers.ENV_VAR, "off")
    assert s2k_transfers.server_url("pi.local") is None
    monkeypatch.setenv(s2k_transfers.ENV_VAR, "http://other:1")
    assert s2k_transfers.server_url("pi.local") == "http://other:1"


def test_the_controller_follows_the_settings_server(qapp, monkeypatch):  # noqa: F811
    monkeypatch.delenv(s2k_transfers.ENV_VAR, raising=False)
    controller = SamplerController(_Midi())
    controller.set_device_type(sampler_models.AKAI_S2000_S3000)
    assert controller._s2k is None
    controller.set_s2k_server("http://pi.test:8420")
    assert controller._s2k.url == "http://pi.test:8420"
    controller.set_s2k_server(None)
    assert controller._s2k is None


def test_the_users_rate_choice_is_kept_and_nothing_else_is_resampled(rig, tmp_path):
    controller, client, rec = rig
    path = _wav(tmp_path, "a.wav", rate=32000, frames=320)
    controller.send_file_queue([_entry(path), _entry(_wav(tmp_path, "b.wav"), sample_rate=11025)])
    assert wait_until(lambda: rec["finished"])
    assert [(s["rate"], s["frames"]) for s in client.jobs["job0"]["samples"]] == [(32000, 320), (11025, 25)]


def test_a_file_at_a_rate_the_server_cant_take_is_skipped_and_the_rest_goes(rig, tmp_path):
    controller, client, rec = rig
    good, high = _wav(tmp_path, "a.wav"), _wav(tmp_path, "hi.wav", rate=96000)
    controller.send_file_queue([_entry(good), _entry(high)])
    assert wait_until(lambda: rec["finished"])
    assert rec["finished"] == [True]
    assert [spec["name"] for spec in client.jobs["job0"]["samples"]] == ["A"]
    assert rec["files"] == [high, good]
    assert any("96000 Hz is outside" in line for line in rec["status"])
    assert not controller.midi_manager.sent


def test_a_batch_only_at_rates_the_server_cant_take_sends_nothing(rig, tmp_path):
    controller, client, rec = rig
    controller.send_file_queue([_entry(_wav(tmp_path, "hi.wav", rate=96000))])
    assert wait_until(lambda: rec["finished"])
    assert rec["finished"] == [False]
    assert client.jobs == {}


def test_a_batch_the_server_refuses_after_upload_gives_its_reason(rig, tmp_path, monkeypatch):
    controller, client, rec = rig
    real_upload = client.upload

    def refusing_upload(job_id, index, pcm):
        job = real_upload(job_id, index, pcm)
        job.update(state="failed", error={"code": "rehearsal_failed", "message": "not enough free sample headers"})
        return job

    monkeypatch.setattr(client, "upload", refusing_upload)
    controller.send_file_queue([_entry(_wav(tmp_path, "a.wav"))])
    assert wait_until(lambda: rec["finished"])
    assert rec["finished"] == [False]
    assert client.started == []
    assert "not enough free sample headers" in rec["status"][-1]


def test_a_busy_bus_is_retried(rig, tmp_path):
    controller, client, rec = rig
    client.busy_left = 2
    controller.send_file_queue([_entry(_wav(tmp_path, "a.wav"))])
    assert wait_until(lambda: rec["finished"])
    assert rec["finished"] == [True]


def test_nothing_new_starts_while_a_cancelled_request_is_still_out(rig, tmp_path, monkeypatch):
    controller, client, rec = rig
    gate = threading.Event()
    client.audio = {0: (44100, [1, 2])}
    real_download = client.start_download

    def slow_download(slot):
        gate.wait(5)
        return real_download(slot)

    monkeypatch.setattr(client, "start_download", slow_download)
    assert controller.receive_samples([(0, str(tmp_path / "x.wav"))]) is True
    controller.cancel_transfer()
    assert rec["rx_finished"] == [False]
    assert controller.receive_samples([(0, str(tmp_path / "y.wav"))]) is False
    assert "Still finishing" in rec["status"][-1]
    gate.set()
    assert wait_until(lambda: not controller._s2k_engine._worker.is_alive())
    assert controller.receive_samples([(0, str(tmp_path / "y.wav"))]) is True
    assert wait_until(lambda: rec["rx_finished"] == [False, True])


def test_a_finished_download_returns_its_audio_and_details():
    seen = []

    class _Reply:
        headers = {"X-S2K-Name": "KICK", "X-S2K-Rate": "44100", "X-S2K-Frames": "1", "X-S2K-Root": "60"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"\x01\x00"

    def opener(request, timeout):
        seen.append(request.full_url)
        return _Reply()

    client = s2k_client.S2kClient("http://pi.test:8420", opener=opener)
    info, pcm = client.download_audio("abc")
    assert seen == ["http://pi.test:8420/v1/jobs/abc/audio?format=pcm"]
    assert info == {"name": "KICK", "rate": 44100, "frames": 1, "root": 60} and pcm == b"\x01\x00"
