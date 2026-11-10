# Piano modal: device test checklist (PIYA-218)

Build: `flutter build apk --debug` (native `piya_live_note` added, so a full rebuild is needed).
Open a score that plays through the live synth (MIDI path), tap the piano disc in the header.

1. Keys sound on touch-down, stop on touch-up. Latency feels instant (target <= 100 ms).
2. Several keys held at once all sound (multi-touch). Slide a finger across keys: each key plays then releases.
3. Hold a key, tap a chevron: note stops, no stuck note. Same on close and on app background.
4. Octave 2: left chevron grey, ignores taps. Octave 6: right chevron grey. Dots: 5, active one has the gradient.
5. Fresh install: tenor/bass opens on Octave 3, others on Octave 4. C label teal only on Octave 4.
6. Change octave to 2, force-quit, reopen the piano: Octave 2.
7. Info button: chart opens above the piano; keys and chevrons still work; its X closes only the chart; closing the piano (X or swipe down from the handle) closes both; second tap on info keeps one chart.
8. Score on the MP3 fallback (no live synth): keys press visually and "Sound is unavailable on this device." replaces the description.
9. Small phone width (320 dp): labels not clipped. Chart image keeps space from the card edge.
10. Playing score + piano together: score keeps playing, piano on channel 5 does not cut it.
