# Sample transfers over SCSI (s2k-send) - real-hardware test plan

Sample send and receive through an s2k-send server (`controller/s2k_transfers.py`, AGENTS.md "Sample audio over SCSI: s2k-send") have
only run against `s2kserver.py --mock`, a simulated S2000. This plan is **step 10 of s2k-send's own `docs/hardware-test-plan.md`**:
run it straight after s2k-send's steps 1-9, against the same Pi, server and S2000 (s2k-send's latest `main`: AKAISDS doesn't support
older servers), so its results can be leaned on here.

It runs from safest to riskiest. **Stop at the first step that misbehaves**, and keep:
- the AKAISDS log (`~/.akaisds/akaisds.log`; lines start `S2kTransfers:`). A failed send logs a WARNING with the job ID and the command
  that fetches its evidence: `s2ksend --server URL --fetch-job ID`. Run it before anything else.
- `s2ksend --jobs` for the job IDs of good sends you want to note.

## What s2k-send's results mean here

Note each s2k-send result before you start, because AKAISDS relies on it:

| s2k-send step | If it passed | If it failed |
|---|---|---|
| 3 keep-bus wait | AKAISDS's busy retries (5 x 1 s) should seldom fire | expect "bus is busy" more often in A and B |
| 4 block size | AKAISDS always sends `block` 16384 | - |
| 5 / 5b rates | B3 checks the same rates from AKAISDS | **skip B3**; with a server that takes the rate but plays it wrong, AKAISDS sends wrong-pitched samples too (`AKAISDS_S2K_SERVER=off` keeps everything on MIDI) |
| 6 gap in the list | the server appends; A1 checks slots still match the MIDI list | record where the samples went; A1 is then essential |
| 7 stereo order | B4 compares AKAISDS's naming with s2k-send's | - |
| 8 download | A2-A4 | **skip A**; receive over MIDI only |

## Before you start

1. Everything on the S2000 saved to disk (s2k-send's plan should have left it with test samples only).
2. **Close DAWs and MIDI monitors** (AGENTS.md, "Real-hardware safety"). The Mac's SCSI connection stays off: the Pi is the initiator
   (ID 7). The Mac reaches the server over the network and the S2000 over MIDI, as usual.
3. `s2ksend --status` from the Mac: `bus: idle`, nothing in `needs_attention`.
4. AKAISDS from this branch (`uv run python src/main.py`). **Settings > Sampler Type > Akai S2000/S3000**, MIDI in/out as usual, then in
   **Sample Transfers over SCSI** tick the box, enter the server (e.g. `piscsi.local`), press **Test**: `Connected: s2kserver ...,
   bus idle`. OK. The log's `config (after Settings)` line shows `s2k=http://...:8420`.
5. Test files: `kick.wav` (44.1 kHz mono), `loop.wav` (stereo), s2k-send's `t32.wav`/`t11.wav`/`t48.wav` tones, a 44.1 kHz 440 Hz
   tone to compare pitch against, a stereo `.rx2` loop, and 3-4 short mono WAVs.

## A. Reading (nothing written)

- [ ] **A1 Slot numbers.** Dashboard **Refresh** (MIDI), and `s2ksend --list` beside it. Every sample has the same position in both,
      including those after the gap s2k-send step 6 left. **The receive path picks samples by this number**: a mismatch here means
      every receive takes the wrong sample. Stop and record both lists.
- [ ] **A2 Receive** one small sample to a WAV: it is the sample you picked and plays back at the right speed. Then a sample from
      after the gap.
- [ ] **A3 Other rates.** Receive `T32` (s2k-send step 5b) with "Save received as: both": the WAV is 32000 Hz; `uv run python
      tools/s2000_sample_check.py show T32.s3` shows SSRATE 32000, SBANDW 1 and the pitch offset in STUNO.
- [ ] **A4 Large receive** (several MB). Note how long it took (the log's `download job ... done` line has `read_kbps`). The progress
      bar and the status bar's "Receiving sample N over SCSI (1/1): N%" move while the S2000 is read.
- [ ] **A4b Cancel a receive** of a large sample part-way: the Dashboard says cancelled at once; the log says the job was `left to
      finish on the server (running)`; the next receive works once it has (`s2ksend --jobs` shows it `done`).
- [ ] **A5 MIDI around SCSI.** Straight after a receive (inside the server's ~20 s keep-bus window), **Refresh** and open the
      **Program Editor**; again after 30 s. MIDI answers both times. The server stops PiSCSI around each operation; whether that
      touches the S2000's MIDI side is unknown.

## B. Sending from the Dashboard (adds new samples; nothing is overwritten)

- [ ] **B1** `kick.wav` (44.1 kHz mono): status ends `Transfer complete - 1 sample(s) sent over SCSI and verified at N KB/s`. Note
      the KB/s against s2k-send step 4's. It plays.
- [ ] **B2** a 22.05 kHz WAV: plays at the right pitch.
- [ ] **B3 Other rates, no resampling.** Queue `t32.wav`, `t11.wav`, `t48.wav` at their own rates (each row's **Edit** dialog left at the file's Sample rate).
      They go over SCSI. Each plays at the same pitch as the 44.1 kHz 440 Hz tone. Then
      quit, start with `AKAISDS_S2K_SERVER=off uv run python src/main.py` (MIDI only), send `t32.wav` again under another name,
      receive both with "both" and `tools/s2000_sample_check.py diff A.s3 B.s3`: **SBANDW, STUNO and SSRATE should be identical**
      between the SCSI and MIDI copies. Record any difference. Quit and start normally again.
- [ ] **B4 Stereo.** `loop.wav`: `LOOP-L` and `LOOP-R` arrive. AKAISDS doesn't pad the name the way s2k-send does (`LOOP      -L`),
      so the log line `stereo pair 'LOOP-L' / 'LOOP-R' linked|NOT linked by the S2000` answers whether the S2000 links the unpadded
      form. Check with `s2ksend --pairs`. Then send the same file over MIDI (`AKAISDS_S2K_SERVER=off`) under another name and check
      `--pairs` again. Record both.
- [ ] **B5 Rate and bit depth from the queue.** Two rows, set with their **Edit** dialog: one at Sample rate 22050, one at 8 bits: both go over SCSI, play
      at the right pitch, and the 8-bit one sounds crunchy.
- [ ] **B6 Batch.** 3-4 mono files and one stereo in one queue run: each queue row ticks off as it lands; the list refreshes
      afterwards and the new samples are at the end, in queue order.
- [ ] **B7 `.rx2` from the Dashboard.** A stereo `.rx2`: one `-L`/`-R` pair per slice, in order.
- [ ] **B8 Refused before writing.** (a) Send a file named the same as a resident sample: the batch is refused, the status says so,
      `s2ksend --list` is unchanged, `s2ksend --status` shows `bus: idle`. (b) If the S2000's free memory is small enough to fill
      with test files, a batch bigger than the free memory: same result.
- [ ] **B8c Rate out of range.** A 96 kHz WAV at its own rate in a batch with `kick.wav`: the 96 kHz one is skipped ("96000 Hz is
      outside ..."), the kick goes over SCSI.
- [ ] **B9 Cancel.** Cancel while it says "Uploading": nothing is sent (`s2ksend --jobs` shows the job `cancelled`). Cancel once it
      says "Sending over SCSI": the app says it can't be stopped and the job finishes.

## C. Program Editor (writes to the sampler)

Use scratch samples. Header fields (markers, loop, tune, root) still go over MIDI after the audio goes over SCSI.

- [ ] **C1** Samples tab: select a sample; its audio loads over SCSI with a percentage (no progressive waveform: it appears at the end).
- [ ] **C2 Send to Sampler.** Trim a 44.1 kHz sample, Send to Sampler: it replaces the old one under the same name; markers, loop and
      pitch are right. Then the same with `T32`: the log's tuning line shows the new sample's SBANDW/SSRATE read back, and it plays
      at the same pitch as before.
- [ ] **C3 Duplicate** a 44.1 kHz sample and `T32`: each copy plays the same as its source.
- [ ] **C4 Slice Editor**, mono: export 4 slices with Create program: every slice plays from its key.
- [ ] **C5 Slice Editor**, stereo (File > Import Audio with a stereo `.rx2`, Create program): every key plays both sides, panned. The
      program's zones name `NAME-L`/`NAME-R`; if B4 showed unpadded pairs don't link, note whether that matters to the program.
- [ ] **C6 Load Akai File...** the `T32.s3` from A3: the new sample plays like the original.
- [ ] **C7** While the Dashboard sends a batch over SCSI with the Program Editor open, nothing in the editor errors (it reads over MIDI
      in the background).

## D. Failure handling

- [ ] **D1** Stop the server (`sudo systemctl stop s2k-server`), Send: "Couldn't reach the S2K server at ..." and nothing hangs. Start
      it again.
- [ ] **D2** Start a send from `s2ksend` on another machine and, while it runs, a receive from AKAISDS: the download job waits on the
      server behind the send and then completes (or fails `busy` if the bus stays in use for 2 minutes).
- [ ] **D3 Evidence.** For any AKAISDS job (a failed one if there was one, else the latest), run the logged or `s2ksend --jobs`
      `--fetch-job` command: the transcript and the WAVs sent arrive, and the WAVs are the audio AKAISDS meant to send.
- [ ] **D4 Don't provoke `needs_attention`.** If a send ends in it on its own, the app should say to power-cycle the S2000 and the Pi
      and run `s2ksend --recover`. Do that, then A1 again.

## Results (20/11/2026, owner's S2000, s2k-send `main` at 0.9.0.dev0, commit not recorded)

App on a Windows PC (the plan was written for a Mac). The Pi's `s2ksend` is at `/opt/s2k-send/bin/s2ksend`.

| Step | Result | Notes / job IDs |
|---|---|---|
| A1 slot numbers vs MIDI list | Pass | App list and server list identical, including after the gap |
| A2 receive | Pass | `KICKA`, and `N03` from after the gap |
| A3 receive 32 kHz, `.s3` header | Pass | WAV 32000 Hz; `.s3` SBANDW 1, SSRATE 32000, STUNO -1421 (-5.55 st) |
| A4 large receive (size, time) | Pass, bar not smooth | 413-807 KB samples read in 2.6-3.5 s (about 200-230 KB/s); status line only reached 100% once per sample, no intermediate values logged. About 8 s fixed overhead before the read and 4-10 s after |
| A4b cancel a receive | Pass, partly | Cancelled between samples of a 6-sample batch; "left to finish on the server (running)" case not exercised |
| A5 MIDI around SCSI | Pass | Refresh and editor open fine after a receive and after 30 s. RSTAT no-reply warnings (3000 ms) at 15:35:38/15:35:50 and 16:09:50 |
| B1 44.1 kHz (KB/s) | Pass | `KICK-808`, job 20261120-153922-70a503: write 215.7, verify 367 KB/s; status bar says 23 KB/s overall (includes rehearsal and set-up) |
| B2 22.05 kHz | Pass | |
| B3 other rates over SCSI; SCSI vs MIDI header diff | Pass | `T32B/T11B/T48B` job 20261120-154413-82a4f6. `T32B` (SCSI) vs `T32C` (MIDI): SBANDW, STUNO, SSRATE identical. **Differences:** SPTYPE 3 One-shot (SCSI) vs 2 No looping (MIDI), confirmed on the panel; MIDI copy has LOOPAT1 250, LDWELL1 and non-zero bytes 151-191 |
| B4 stereo link: SCSI unpadded / MIDI | **Not linked** (SCSI); MIDI skipped | `LOOPS-L/-R` job 20261120-161016-3f79de: partners 0xffff/0xffff. Padded `LOOP2..5`, `LP-n 102` pairs are linked. MIDI half skipped: a 6,227-packet MIDI send froze the GUI (see below) |
| B5 queue rate and bit depth | Pass | Job 20261120-161447-df7693: 22050 Hz and 44100 Hz (8-bit crushed by the app) |
| B6 batch | Pass | Job 20261120-161703-252270 |
| B7 `.rx2` from the Dashboard | **Mono only** | 4 mono slices `REX-1..4`; no stereo `.rx2` available |
| B8 duplicate name / no memory refused | B8a pass; B8b skipped | Job 20261120-163334-cb2d85 refused: `already on the S2000: T32B`; nothing added. A second send of `KICK-808` earlier arrived as `KICK-8081` (renamed before the server) |
| B8c 96 kHz refused | Pass | Synthetic `tone96k.wav` skipped, kick sent (job 20261120-163611-ce1bbc) |
| B9 cancel | Pass | Cancelled while uploading: job `cancelled`, nothing added. After it started: "can't be stopped once it has started", job finished (20261120-164024-661340) |
| C1 load audio | Pass | About 12 s for a 2 s sample; GUI stayed responsive (worst heartbeat 18 ms). **Needed a fix first** (below) |
| C2 Send to Sampler (44.1k / 32k) | Pass | `KICK-808` replaced, no `-TMP` left; `T32C` tuning line: STUNO 64116 -> 64115, SBANDW 1 |
| C3 Duplicate | Pass | `KICK-80 COPY` (STUNO 0), `T32B COPY` (STUNO 64115, SBANDW 1) |
| C4 slices mono | **Blocked** | 8 slices sent, but "Failed to create program": program write got no reply within 2.0 s. **Duplicate Program also fails on the latest released version (owner, 20/11/2026), so this is not a regression of this branch** |
| C5 slices stereo | Blocked | No stereo `.rx2`; program creation failing (same cause as C4) |
| C6 Load Akai File | Pass | `KICKA (3).s3` (44.1k) and `T32.s3` (32k): tuning line STUNO 64115 kept. Button needs a sample selected first |
| C7 editor during a SCSI send | Design-limited | Window switching is blocked during a transfer, so the editor can't be used during a Dashboard send. No errors in the log |
| D1 server down | Pass | `Couldn't reach the S2K server at http://piscsi.local:8420`, nothing hung |
| D2 busy bus | Pass | Download created 17:37:26 during a 75 s send, finished 17:38:05. Status bar shows nothing while queued |
| D3 evidence fetch | Pass | `--fetch-job 20261120-172722-20cc8a` saved 4 WAVs and `transcript.log`; WAVs not compared to the originals |
| D4 needs_attention (if it happened) | Did not happen | |

Findings from this run:
- **Program creation fails** (C4, and Duplicate Program twice, 17:08-17:12): the program write (function `0x07`) times out at 2.0 s with SCSI quiet. A failure with the same signature is in an earlier session. Cause not found; **the owner reproduced Duplicate Program failing on the latest released version too (20/11/2026), so it is not caused by this branch or by SCSI.** Ideas not tried: S2000 state after the 2026-10-10 incident, the Pi's presence on the SCSI bus, a power cycle.
- **Bug fixed during the run:** `_wait_for_any_signal` let a later signal overwrite the first, so a SCSI audio load in the Program Editor ended as "couldn't receive" and every edit button stayed grey. The s2k receive emits `sample_received` and `receive_finished` back to back. Fixed (first signal wins) with a regression test.
- **A large MIDI send froze the GUI** (a 6,227-packet stereo send at 16:01, SCSI off; "Not responding" after 4,093 packets) and left a process holding the MIDI ports until the USB interface was replugged, plus a partial `LOOPM-L`.
- **Windows-only test failure fixed:** `test_plan_splits_stereo_keeps_rates_and_names_unique` overwrote `kick.wav` with `KICK.wav`.
- The Pi's `sudo` asks for a password; `s2ksend --list` cycles the bus (PiSCSI stays stopped for a while after it).

Then record what was measured, dated and with the unit, in AGENTS.md's s2k-send section, and remove "not yet on hardware" from what passed.
