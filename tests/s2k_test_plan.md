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

## Results (20/11/2026, owner's S2000, s2k-send `main` at ______)

| Step | Result | Notes / job IDs |
|---|---|---|
| A1 slot numbers vs MIDI list | | |
| A2 receive | | |
| A3 receive 32 kHz, `.s3` header | | |
| A4 large receive (size, time) | | |
| A5 MIDI around SCSI | | |
| B1 44.1 kHz (KB/s) | | |
| B2 22.05 kHz | | |
| B3 other rates over SCSI; SCSI vs MIDI header diff | | |
| B4 stereo link: SCSI unpadded / MIDI | | |
| B5 queue rate and bit depth | | |
| B6 batch | | |
| B7 `.rx2` from the Dashboard | | |
| B8 duplicate name / no memory refused | | |
| B8c 96 kHz refused | | |
| B9 cancel | | |
| C1 load audio | | |
| C2 Send to Sampler (44.1k / 32k) | | |
| C3 Duplicate | | |
| C4 slices mono | | |
| C5 slices stereo | | |
| C6 Load Akai File | | |
| C7 editor during a SCSI send | | |
| D1 server down | | |
| D2 busy bus | | |
| D3 evidence fetch | | |
| D4 needs_attention (if it happened) | | |

Then record what was measured, dated and with the unit, in AGENTS.md's s2k-send section, and remove "not yet on hardware" from what passed.
