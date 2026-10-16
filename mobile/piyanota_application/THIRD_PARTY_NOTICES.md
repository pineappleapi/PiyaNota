# Third-party notices

This file lists third-party code built into the PiyaNota Android app
that carries its own licence terms beyond the Dart/Flutter packages
(whose licences Flutter collects automatically).

## LAME 3.100 (MP3 encoder)

- Used by: Export Audio (PIYA-211), to encode the exported MP3.
- Source: the official `lame-3.100.tar.gz` release from
  https://sourceforge.net/projects/lame/files/lame/3.100/ , unpacked
  unmodified into `android/app/src/main/cpp/lame/`. The release's own
  `COPYING` and `LICENSE` files are kept in that directory and are the
  authoritative licence text.
- Licence: GNU Lesser General Public License, version 2 or later
  (LGPL-2.0-or-later).
  Copyright (c) 1999-2017 the LAME project, Mike Cheng, Mark Taylor,
  Robert Hegemann, Gabriel Bouvigne, Alexander Leidinger and others.

How PiyaNota meets the LGPL:

- LAME is built as its own shared library, `libmp3lame.so`, and the app
  calls it through a separate JNI bridge (`libpiyanota_lame.so`, source
  in `android/app/src/main/cpp/lame_jni.c`). A user can replace
  `libmp3lame.so` with their own build of LAME without touching PiyaNota's
  code.
- LAME's source is not modified. The build flags used are in
  `android/app/src/main/cpp/CMakeLists.txt`.
- Anyone distributing the APK must also offer LAME's source (the release
  tarball above, plus `CMakeLists.txt`) and show this notice, for example
  on an "Open-source licences" screen.

## Sonic (time-stretching, via AndroidX Media3)

- Used by: Playback speed (PIYA-210) through ExoPlayer, and Export Audio
  (PIYA-211) through `androidx.media3.common.audio.SonicAudioProcessor`,
  which keeps the pitch while changing speed (FR-9).
- Not vendored: it ships inside `androidx.media3:media3-common:1.4.1`,
  which the app already depends on through `just_audio`.
- Licence: Apache License 2.0. Sonic is copyright (c) 2010 Bill Cox; the
  Media3 port is copyright The Android Open Source Project.
