# Sample transfers over SCSI (s2k-send) - real-hardware test plan

Sample send and receive through an s2k-send server (`controller/s2k_transfers.py`, AGENTS.md "Sample audio over SCSI: s2k-send") have
only run against `s2kserver.py --mock`, a simulated S2000. This is the plan for the first run on a real Pi + PiSCSI + S2000. It runs
from safest to riskiest. **Stop at the first step that misbehaves** and keep the AKAISDS log (`~/.akaisds/akaisds.log`; lines start
`S2kTransfers:`) and the server's job folder (`<data-dir>/jobs/<id>/`, with `transcript.log`) rather than pressing on.

## Before you start

1. **Save everything on the S2000 to disk first.** Sends only ever add samples, but this is the first time on hardware.
2. **Close DAWs and MIDI monitors** (AGENTS.md, "Real-hardware safety"). The Mac or other SCSI initiator must be off: the Pi becomes
   the initiator (ID 7 by default).
3. On the Pi: `sudo ./s2kserver.py` (s2k-send's README). From the Mac: `./s2ksend.py --status` and `--list` should work first.
4. In AKAISDS: **Settings > Sampler Type > Akai S2000/S3000**, MIDI input and output as usual, then in **Sample Transfers over SCSI**
   tick the box, enter the server (e.g. `piscsi.local`), press **Test**: it should say `Connected: s2kserver ..., bus idle`. Press OK.
   The log's `config (after Settings)` line should show `s2k=http://...:8420`.

## A. Read-only

- [ ] Dashboard **Refresh** (MIDI): the list is right. Note the slot numbers.
- [ ] **Receive one small sample** to a WAV. Check that it is the sample you picked: **this confirms the server's slot numbers match
      the MIDI list**. It plays back correctly at the right speed.
- [ ] Receive with "Save received as: both": the `.s3` opens with `tools/s2000_sample_check.py show`.
- [ ] Receive a **large** sample (several MB). Note how long it took (no progress is shown during a download; the status bar stays
      on "Receiving sample N over SCSI"). Over 15 minutes would hit the client's timeout.
- [ ] Straight after a receive, **Refresh** and open the **Program Editor**: MIDI still answers (the server takes the S2000 in and out
      of SCSI-MIDI mode around each operation).

## B. Sending (adds new samples; nothing is overwritten)

- [ ] Send one **44.1 kHz mono** WAV. The status ends `Transfer complete - 1 sample(s) sent over SCSI and verified`. It plays.
- [ ] Send a **22.05 kHz** WAV: plays at the right pitch.
- [ ] Send a **stereo** WAV: `NAME-L` and `NAME-R` arrive.
- [ ] Send a **batch** of 3-4 files: every queue row goes as it lands; the list refreshes afterwards.
- [ ] Send a **32 kHz** (or 11025 Hz) WAV: with s2k-send 0.7 the status says it is **sending over MIDI instead**, and it does. With a
      server that takes any rate, it goes over SCSI and plays at the right pitch (tune offset in the header).
- [ ] **Cancel** before the upload finishes: nothing is sent. Cancel once it says "Sending over SCSI": the app says it can't be
      stopped and the job finishes.

## C. Program Editor (writes to the sampler)

Use a scratch sample.

- [ ] Samples tab: select a sample; its audio loads over SCSI (no progressive waveform: it appears at the end).
- [ ] Trim it, **Send to Sampler**: the new sample replaces the old under the same name, markers and loop are right, pitch is right.
- [ ] **Duplicate** a sample: the copy plays the same.
- [ ] Slice Editor: export 4 slices at the sample's own rate, with Create program: every slice plays.
- [ ] While the Dashboard sends over SCSI with the Program Editor open, nothing in the editor errors (it reads over MIDI in the
      background; whether the S2000 answers MIDI while it is in SCSI-MIDI mode is unknown).

## D. Failure handling

- [ ] Stop the server, Send: "Couldn't reach the S2K server at ..." and nothing hangs.
- [ ] Start a send from `s2ksend.py` on another machine and, while it runs, a receive from AKAISDS: AKAISDS retries for ~5 s, then
      "bus is busy".

Record what you saw, dated and with the unit, in AGENTS.md's s2k-send section.
