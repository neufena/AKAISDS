"""Sending and receiving Akai S2000/S3000 samples through an s2k-send server (SCSI from a Raspberry Pi + PiSCSI) instead of MIDI.

PROOF OF CONCEPT, NOT TRIED AGAINST A REAL SERVER. Only sample audio goes this way: the sample list, headers, programs and everything else
stay on MIDI. Switched on by `AKAISDS_S2K_SERVER` (a server URL, or `1` for `DEFAULT_SERVER_URL`); there is no Settings UI yet.

Built lazily by `SamplerController` (like the S950/Yamaha engines) and reports through the controller's own signals, so the Dashboard and
the Program Editor need no changes. The HTTP calls block, so each operation runs on a plain worker thread that only puts events on a
queue; a QTimer on the GUI thread drains it (no cross-thread Qt signals, the same pattern as the Slice Editor's SuperFlux analysis).

 - `send_file_queue(entries)`: ONE server job for the whole batch (the server rehearses it on a simulated S2000, then sends and reads
   every sample back). A stereo file becomes two mono samples `-L`/`-R`, named the way the MIDI path names them. The server takes only
   44100 or 22050 Hz, so other rates are resampled (22050 Hz and below go as 22050). A job that has STARTED can't be cancelled.
 - `receive_samples([(slot, path)])`: each sample's audio as PCM, saved like a MIDI receive (WAV and/or the Akai sample file, whose
   header comes from the server's own header read).
"""

import os
import queue
import threading
import time

from PySide6.QtCore import QTimer

from core import akai_sysex, debug_log, s2k_client, sds_encoder

ENV_VAR = "AKAISDS_S2K_SERVER"
DEFAULT_SERVER_URL = "http://piscsi.local:8420"
_OFF = ("", "0", "false", "no", "off")
_ON = ("1", "true", "yes", "on")

_POLL_MS = 50
_JOB_POLL_S = 0.3
_WRITE_PHASES = ("header", "audio")


def server_url():
    """The s2k-send server to use, or None to keep sample transfers on MIDI."""
    value = os.environ.get(ENV_VAR, "").strip()
    if value.lower() in _OFF:
        return None
    if value.lower() in _ON:
        return DEFAULT_SERVER_URL
    return value


def _log():
    return debug_log.get_logger()


def _unique(name, taken):
    if name not in taken:
        return name
    for n in range(2, 1000):
        suffix = str(n)
        candidate = name[: 12 - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
    raise ValueError(f"no free name for {name!r}")


def plan_units(entries, read_channels=sds_encoder.read_wav_channels):
    """The Dashboard's queue entries as the samples one job sends. Returns (units, skipped): each unit is a dict with file (its entry
    index), name, rate and samples (16-bit ints); skipped is [(filepath, reason)] for files that couldn't be read."""
    units, skipped, taken = [], [], set()
    for index, entry in enumerate(entries):
        path = entry["filepath"]
        try:
            channels, rate = read_channels(path)
        except (OSError, ValueError) as e:
            skipped.append((path, str(e)))
            continue
        base = entry.get("name") or os.path.splitext(os.path.basename(path))[0]
        target = s2k_client.server_rate(entry.get("sample_rate") or rate)
        bits = entry.get("bit_depth", 16)
        if len(channels) == 2 and not entry.get("mono", False):
            legs = [
                (akai_sysex.build_stereo_channel_name(base, "-L"), channels[0]),
                (akai_sysex.build_stereo_channel_name(base, "-R"), channels[1]),
            ]
        else:
            legs = [(base, channels[0])]
        for leg_name, samples in legs:
            if target != rate:
                samples, _ = sds_encoder.resample_to_target_rate(samples, rate, target)
            if bits < 16:
                samples = [sds_encoder.bitcrush_sample(s, bits) for s in samples]
            name = _unique(s2k_client.akai_name(leg_name), taken)
            taken.add(name)
            units.append({"file": index, "name": name, "rate": target, "samples": list(samples), "source_rate": rate})
    return units, skipped


class S2kTransfers:
    def __init__(self, controller, url, client=None):
        self._c = controller
        self.url = url
        self._client = client or s2k_client.S2kClient(url)
        self.busy = False
        self._mode = None
        self._token = 0
        self._events = queue.Queue()
        self._timer = QTimer()
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._drain)
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._started = False  # the send job is running on the server: it can't be cancelled now
        self._entries = []
        self._units = []
        self._files_reported = set()
        self._sent_units = 0
        self._receive_total = 0
        self._receive_done = 0

    # -- plumbing ---------------------------------------------------------------------------------------------------

    def _begin(self, mode, target, *args):
        self.busy = True
        self._mode = mode
        self._token += 1
        self._cancel = threading.Event()
        self._started = False
        token = self._token
        self._timer.start()
        threading.Thread(target=self._run_worker, args=(token, target, args), name=f"s2k-{mode}", daemon=True).start()

    def _run_worker(self, token, target, args):
        try:
            target(token, *args)
        except s2k_client.S2kError as e:
            self._post(token, "failed", self._describe(e))
        except Exception as e:
            _log().error("S2kTransfers: worker failed", exc_info=True)
            self._post(token, "failed", f"S2K transfer failed: {e}")

    def _post(self, token, kind, *args):
        self._events.put((token, kind, args))

    def _drain(self):
        while True:
            try:
                token, kind, args = self._events.get_nowait()
            except queue.Empty:
                break
            if token != self._token:
                continue
            getattr(self, f"_on_{kind}")(*args)
        if not self.busy:
            self._timer.stop()

    def _describe(self, error):
        if error.code == "unreachable":
            return f"Couldn't reach the S2K server at {self.url}"
        if error.code == "busy":
            return "The S2K server's SCSI bus is busy - try again in a moment"
        if error.code == "needs_attention":
            return "The S2K server needs attention: power-cycle the S2000 and the Pi, then recover the server"
        return f"S2K server: {error.message or error.code}"

    def _on_status(self, message):
        self._c.status_changed.emit(message)

    def _on_failed(self, message):
        _log().warning(f"S2kTransfers: {self._mode} failed: {message}")
        mode = self._mode
        self._finish()
        self._c.status_changed.emit(message)
        if mode == "send":
            self._c.transfer_finished.emit(False)
            self._c.refresh_sample_list(silent=True)
        else:
            self._c.receive_finished.emit(False)

    def _finish(self):
        self.busy = False
        self._mode = None
        self._token += 1

    def cancel(self):
        """True if an S2K transfer was running (the controller then has nothing more to do). A send already running on the server
        can't be stopped: it is left to finish."""
        if not self.busy:
            return False
        with self._lock:
            started = self._started
            if not started:
                self._cancel.set()
        if started:
            self._c.status_changed.emit("An S2K transfer can't be stopped once it has started - it will finish on its own")
            _log().info("S2kTransfers: cancel refused, the server job is already running")
            return True
        mode = self._mode
        _log().info(f"S2kTransfers: {mode} cancelled")
        self._finish()
        self._c.status_changed.emit("Transfer cancelled")
        if mode == "send":
            self._c.transfer_finished.emit(False)
        else:
            self._c.receive_finished.emit(False)
        return True

    # -- sending ----------------------------------------------------------------------------------------------------

    def send_file_queue(self, entries):
        if not entries:
            return False
        if self.busy or self._c.is_sds_transfer_busy():
            self._c.status_changed.emit("A transfer is already in progress - please wait for it to finish")
            return False
        self._entries = list(entries)
        self._units = []
        self._files_reported = set()
        self._sent_units = 0
        _log().info(f"S2kTransfers: send start: {len(entries)} file(s) via {self.url}")
        self._c.status_changed.emit("Preparing samples for the S2K server...")
        self._begin("send", self._send_worker, self._entries)
        return True

    def _send_worker(self, token, entries):
        units, skipped = plan_units(entries)
        self._post(token, "planned", units, skipped)
        if not units:
            self._post(token, "failed", "Nothing to send - no file could be read")
            return
        specs = [{"name": u["name"], "rate": u["rate"], "frames": len(u["samples"])} for u in units]
        job = self._client.create_job(specs)
        job_id = job["id"]
        _log().info(f"S2kTransfers: job {job_id} created for {[s['name'] for s in specs]}")
        for i, unit in enumerate(units):
            if self._cancel.is_set():
                self._client.cancel(job_id)
                return
            self._post(token, "status", f"Uploading {unit['name']} to the S2K server ({i + 1}/{len(units)})...")
            job = self._client.upload(job_id, i, s2k_client.pcm_from_samples(unit["samples"]))
        if job.get("state") != "ready":
            error = job.get("error") or {}
            self._post(token, "failed", f"The S2K server refused the batch: {error.get('message') or job.get('state')}")
            return
        with self._lock:
            if self._cancel.is_set():
                self._client.cancel(job_id)
                return
            self._started = True
        self._post(token, "status", "Sending over SCSI...")
        self._client.start(job_id)
        since = 0
        last_progress = None
        while True:
            snap = self._client.job(job_id, since)
            for line in snap.get("log", []):
                _log().info(f"S2kTransfers: server: {line.get('msg')}")
            since = snap.get("next", since)
            progress = snap.get("progress")
            if progress and progress != last_progress:
                last_progress = progress
                self._post(token, "progress", dict(progress))
            if snap["state"] in s2k_client.TERMINAL_STATES:
                self._post(token, "send_ended", snap)
                return
            time.sleep(_JOB_POLL_S)

    def _on_planned(self, units, skipped):
        self._units = units
        for path, reason in skipped:
            _log().warning(f"S2kTransfers: skipping {path!r} - couldn't read it: {reason}")
            self._c.status_changed.emit(f"Skipping {os.path.basename(path)}: {reason}")
            self._files_reported.add(path)
            self._c.file_transferred.emit(path)
        for unit in units:
            if unit["rate"] != unit["source_rate"]:
                _log().info(f"S2kTransfers: {unit['name']} resampled {unit['source_rate']} -> {unit['rate']} Hz")

    def _units_of_file(self, file_index):
        return [i for i, u in enumerate(self._units) if u["file"] == file_index]

    def _report_files_done_before(self, unit_index):
        for i, entry in enumerate(self._entries):
            path = entry["filepath"]
            indexes = self._units_of_file(i)
            if path in self._files_reported or not indexes or max(indexes) >= unit_index:
                continue
            self._files_reported.add(path)
            self._c.unit_progress.emit(1.0)
            self._c.file_transferred.emit(path)

    def _on_progress(self, progress):
        index = progress.get("sample_index", 0)
        self._report_files_done_before(index)
        if not 0 <= index < len(self._units):
            return
        unit = self._units[index]
        done, total = progress.get("done", 0), progress.get("total", 0)
        fraction = done / total if total else 0.0
        phase = progress.get("phase")
        writing = phase in _WRITE_PHASES
        leg = 0.5 * fraction if writing else 0.5 + 0.5 * fraction
        legs = self._units_of_file(unit["file"])
        self._c.transfer_progress.emit(done, total)
        self._c.unit_progress.emit((legs.index(index) + leg) / len(legs))
        what = "Sending" if writing else "Verifying"
        self._c.status_changed.emit(f"{what} {unit['name']} over SCSI ({index + 1}/{len(self._units)}): {int(fraction * 100)}%")

    def _on_send_ended(self, snap):
        state = snap["state"]
        result = snap.get("result") or {}
        error = snap.get("error") or {}
        if state == "done":
            self._report_files_done_before(len(self._units))
            sent = len(result.get("samples", self._units))
            kbps = result.get("overall_kbps")
            speed = f" at {kbps:.0f} KB/s" if isinstance(kbps, (int, float)) else ""
            message = f"Transfer complete - {sent} sample(s) sent over SCSI and verified{speed}"
            ok = True
        else:
            done_names = {d.get("name") for d in error.get("done", [])}
            finished = [i for i, u in enumerate(self._units) if u["name"] in done_names]
            for i, entry in enumerate(self._entries):
                legs = self._units_of_file(i)
                if legs and all(leg in finished for leg in legs) and entry["filepath"] not in self._files_reported:
                    self._files_reported.add(entry["filepath"])
                    self._c.file_transferred.emit(entry["filepath"])
            message = f"S2K transfer {state}: {error.get('message') or error.get('code') or state}"
            if done_names:
                message += f" ({len(done_names)} sample(s) did arrive)"
            ok = False
        _log().info(f"S2kTransfers: send ended {state}: {result or error}")
        self._finish()
        self._c.status_changed.emit(message)
        self._c.transfer_finished.emit(ok)
        QTimer.singleShot(2500, lambda: self._c.refresh_sample_list(silent=True))

    # -- receiving --------------------------------------------------------------------------------------------------

    def receive_samples(self, requests):
        """requests: [(slot, save path)] - slots are positions in the sampler's sample list."""
        if not requests:
            return
        if self.busy or self._c.is_sds_transfer_busy():
            self._c.status_changed.emit("A transfer is already in progress - please wait for it to finish")
            return
        self._receive_total = len(requests)
        self._receive_done = 0
        want_header = self._c.receive_format in ("s3", "both")
        _log().info(f"S2kTransfers: receive start: {len(requests)} sample(s) via {self.url}")
        self._begin("receive", self._receive_worker, list(requests), want_header)

    def _receive_worker(self, token, requests, want_header):
        for number, (slot, path) in enumerate(requests, start=1):
            if self._cancel.is_set():
                return
            self._post(token, "status", f"Receiving sample {slot} over SCSI ({number}/{len(requests)})...")
            info, pcm = self._client.sample_audio(slot)
            raw_header = None
            if want_header:
                header_hex = self._client.sample(slot).get("header_hex")
                raw_header = bytes.fromhex(header_hex) if header_hex else None
            self._post(token, "received", slot, path, info, s2k_client.samples_from_pcm(pcm), raw_header)
        self._post(token, "receive_ended")

    def _on_received(self, slot, path, info, samples, raw_header):
        self._receive_done += 1
        _log().info(
            f"S2kTransfers: received slot={slot} name={info.get('name')!r} frames={len(samples)} rate={info.get('rate')} -> {path!r}"
        )
        self._c.receive_progress.emit(len(samples), max(1, len(samples)))
        self._c.sample_chunk_received.emit(samples)
        receive = {"sample_rate": info.get("rate") or 44100, "bit_depth": 16, "raw_header": raw_header}
        try:
            saved_path, note = self._c.save_received_sample(path, slot, receive, samples)
        except OSError as e:
            self._on_failed(f"Couldn't save sample {slot}: {e}")
            return
        self._c.status_changed.emit(f"Saved sample {slot} to {saved_path}{note}")
        self._c.sample_received.emit(saved_path)

    def _on_receive_ended(self):
        self._finish()
        self._c.status_changed.emit("All samples received")
        self._c.receive_finished.emit(True)
