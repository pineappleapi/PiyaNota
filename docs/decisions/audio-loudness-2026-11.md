# Audio loudness targets for PiyaNota playback (web lookup, 2026-11-05)

Status: input to backend task B10 and frontend task F8c. Not a final decision: the final levels are chosen by ear on the phone.

## What the web lookup found
- The common mastering deliverable for streaming is about -14 LUFS integrated with a true peak at or below -1 dBTP. Spotify's own guidance gives a playback target of -14 LUFS and a recommended true peak of -1 dBTP (-2 dBTP for very loud masters). Sources agree that YouTube, Tidal, Amazon Music and SoundCloud sit near -14 LUFS.
- Apple Music is usually listed at about -16 LUFS, but one source says Apple does not publish a target, so that figure may be observed rather than published. Deezer figures conflict between sources.
- Some sources recommend a true-peak ceiling of -1.5 to -2 dBTP when the audio will be re-encoded as AAC or MP3, because encoding can overshoot.
- Limits of this lookup: it used secondary pages (mastering blogs and vendor guides), not the platforms' primary documents. It found no standard for a metronome click level.

Sources:
- https://www.soundbridge.io/mastering-for-streaming-your-2026-platform-guide
- https://www.izotope.com/en/learn/mastering-for-streaming-platforms.html
- https://www.forasoft.com/learn/audio-for-video/articles-audio/lufs-targets-per-platform-2026
- https://www.roexaudio.com/blog/what-lufs-should-i-master-at

## How this feeds the plan (user rule A6: voices a bit louder than the suggested level, metronome clearly quieter than voices)
- The user asked for voices a bit louder than the suggested level. The suggested streaming level is -14 LUFS for a full mix. PiyaNota's voice-sum (four voices played together) therefore starts at about -12 LUFS, 2 dB above the reference, with a limiter so that true peak stays at or below -1 dBTP (-2 dBTP because the files are MP3).
- Each voice stem on its own starts near -18 LUFS, so one soloed voice is not louder than the four together.
- These are starting values. B10 measures the real LUFS and true peak of the rendered stems and the sum, and records them in joint-contract.md J7. The user adjusts by ear on the phone with headphones and with the speaker.
- Metronome click: peaks lowered in the app (F8c) so the click at its slider maximum sits well below a voice at its maximum.

## B10 measured (2026-11-05)
Primary source added: https://artists.spotify.com/help/article/loudness-normalization (Spotify states -14 LUFS and 1 dB headroom for lossy formats). The AES TD1008 figures (-16 LUFS, -1 dBTP) were seen only on secondary pages, not verified against the standard.

Method: `_render_to_mp3` (fluidsynth, piano.sf2, ffmpeg 192k MP3) on a hand-built 8-bar 4/4 SATB piece (no saved Moonriver events exist locally). Levels measured with ffmpeg `ebur128=peak=true`; the sum is `amix=inputs=4:normalize=0` of the four MP3s decoded to float.

| STEM_TARGET_LUFS | stems LUFS | stem true peaks (dBTP) | sum LUFS | sum true peak (dBTP) | clips |
|---|---|---|---|---|---|
| -18 | -18.2 to -18.3 | -5.9 to -8.0 | -11.8 | +0.8 | yes (max 1.09) |
| -19 | -19.2 | -6.9 to -9.0 | -12.8 | -0.2 | no |
| -20 | -20.2 | -7.9 to -10.0 | -13.8 | -1.2 | no |

Result: STEM_TARGET_LUFS = -20.0, the first step where the sum true peak is at or below -1 dBTP. Trade-off: the sum is -13.8 LUFS, about the -14 reference and not the "a bit louder, about -12" the user wanted. Reaching -12 needs a limiter on the sum, which the app does not have (it mixes four stems). One synthetic chord piece; real choral material may differ by a few dB, so tune by ear on the phone.
