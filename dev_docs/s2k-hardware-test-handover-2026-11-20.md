# s2k-send hardware test: handover for the development machine (20/11/2026)

The AKAISDS side of `tests/s2k_test_plan.md` was run on the owner's S2000 with a real Pi (s2k-send 0.9.0.dev0). Results are in the plan's
Results table and AGENTS.md ("Sample audio over SCSI: s2k-send"). This file lists what is left to FIX or DECIDE, with the evidence, so the
development machine can pick it up. The matching server-side notes are in the s2k-send repo: `docs/akaisds-hardware-test-handover.md`.

**Branch:** `fix-s2k-test-windows-case` (on top of `s2k-send-support` at `18f4a39`): `de34f41` (editor fix), `8b5d205` (Windows test fix and
results), `3675940` (note that Duplicate Program also fails on the release). Tests: `tests/test_program_editor_window.py` and
`tests/test_s2k_transfers.py` pass (277); the full suite was not run on this machine.

## Done in this run

- **Fixed:** `ProgramEditorWindow._wait_for_any_signal` now keeps the FIRST signal. The s2k receive emits `sample_received` and
  `receive_finished` back to back in one drain, so both capture slots ran before `loop.exec()` returned and the later one overwrote the
  first. Every SCSI audio load in the Program Editor then read as "couldn't receive" (`audio fetch returned None - bailing out` in the log,
  every edit button grey). Regression test: `test_wait_for_any_signal_returns_the_first_signal_when_two_fire_together`.
- **Fixed:** `test_plan_splits_stereo_keeps_rates_and_names_unique` wrote `kick.wav` and `KICK.wav` into one folder; on Windows (case-insensitive)
  the second overwrote the first. It now uses `kick!.wav`, which still maps to the sample name `KICK`.

## To fix or decide (most important first)

1. **[RESOLVED 2026-11-25: caused by the hardware MIDI router, now bypassed; C4 and C5 can be run.]** **Program creation over MIDI times out.** The program write (`send_and_receive` of function `0x07`) gets no reply within 2.0 s: Slice Editor
   "Create program" (17:08:54), and Duplicate Program twice (17:10:42, 17:12:27), SCSI quiet. A failure with the same signature is in an older
   session in the log. **The owner reproduced Duplicate Program failing on the latest RELEASED version**, so it is not from this branch or from
   SCSI. Reads, header writes and sample sends all work. AGENTS.md says the Slice Editor path was proven on this S2000 on 2026-10-07; the drive
   failed after the 2026-10-10 incident. Not tried: a power cycle (RAM samples are lost: save first), repeating with PiSCSI stopped, a
   memory/program-count look on the panel, whether the S2000 shows an error when the write arrives. **Do not retry blind on hardware**; read
   "Real-hardware safety" first. C4 and C5 of the plan stay blocked until this works.
2. **Unpadded `NAME-L`/`NAME-R` stereo pairs are not linked by the S2000** (B4: job `20261120-161016-3f79de`, partner fields 0xffff/0xffff,
   logged as a WARNING). s2k-send's padded pairs (`LOOP2     -L`) are linked (`s2ksend --pairs`: 7 pairs). So the "don't switch to padding without the
   hardware answer" note now has its answer. A fix has to change the SCSI send names AND the Program Editor's slice names together
   (`SNAME1/2`, `akai_sysex.build_stereo_channel_name`). The MIDI half of B4 (does an unpadded pair link over MIDI?) was not run.
3. **SCSI sends land as One-shot (SPTYPE 3), MIDI sends as No looping (SPTYPE 2)** (B3, `T32B` vs `T32C`, confirmed on the panel). The MIDI copy
   also had LOOPAT1 250, LDWELL1 15/39 and non-zero bytes 151-191; the SCSI copy had zeros there. SBANDW, STUNO and SSRATE were identical.
   Decide which is wanted, and whether AKAISDS should write SPTYPE after an SCSI send (the way it writes header fields after a MIDI send).
4. **A large MIDI send froze the GUI.** A 6,227-packet stereo-loop send (`LOOPM-L`, 16:01, SCSI off) fell back to open loop (no ACK within
   500 ms), the window went "Not responding" after 4,093 packets with the log silent from 16:04:49, and the killed process lingered with the USB
   MIDI ports held until the interface was unplugged. Not reproduced; probably older than this branch. A partial `LOOPM-L` was left on the S2000.
5. **Small usability items:** the receive bar jumps to 100% on samples under 1 MB (the read takes 2-4 s, with about 8 s before it and 4-10 s
   after); the status bar shows nothing while a download waits behind another job; the "N KB/s" on a send is the overall rate (23 KB/s for a 88 KB
   file) while the write rate was 216; a duplicate name sent from the Dashboard was renamed (`KICK-8081`) before it reached the server, but a
   later one was refused by the server (B8a), so find where the rename happens; **Load Akai File... was inactive until a sample was selected**
   although its enabling code and comment say it needs none; `RSTAT` (memory status) no-reply warnings at 15:35:38, 15:35:50 and 16:09:50.

## Not run

Stereo `.rx2` (B7 was mono; C5 needs it), B4's MIDI half, B8b (memory-full refusal), A4 on a sample of several MB, A4b's "cancel a RUNNING
download" case (the cancel landed between samples), D4 (`needs_attention`, never happened). C7 can't be done as written: the app swaps between
the Dashboard and the Program Editor and refuses to switch during a transfer.

## State left on the S2000 (scratch, nothing deleted by the tooling)

`LOOPM-L` (partial, from the frozen MIDI send), `LOOP2     -1`..`-8` (slice export, no program), `KICK-8081`, `KICK-80 COPY`, `T32B COPY`,
`T32 LOAD`, `KICKA2`, `D2TEST`, `D2LONG`, plus the batch samples from B3 to B6 (`T32B`, `T11B`, `T48B`, `T32C`, `KICKC`, `REX-1`..`REX-4` and
others). Programs: `TEST PROGRAM`, `LOOPS 1-3` (not made by the Dashboard; origin unknown).

## Running this on Windows (what it took)

`uv` and Python 3.12 (`uv sync`; the first `uv python install` hit "Missing expected target directory", `--reinstall` fixed it); the Visual
Studio C++ Build Tools, then `tools/build_velociloops.py` from a shell with `vcvars64.bat` run first (the `vswhere` warning is harmless);
`src/ui/_version.py` (git-ignored) with `APP_VERSION = "0.0.0-dev"` because the checkout has no tags. Start with `uv run python src/main.py`;
`AKAISDS_S2K_SERVER=off` keeps everything on MIDI. The Pi is `piscsi` (service `s2k-server`, client `/opt/s2k-send/bin/s2ksend`; its `sudo` needs
a password). **`s2ksend --list` cycles PiSCSI** (it stays stopped for a while afterwards): don't run it while testing MIDI.
