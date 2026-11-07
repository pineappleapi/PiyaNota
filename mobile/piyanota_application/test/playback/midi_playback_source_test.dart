import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/state/playback_providers.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'playback_fakes.dart';

ScoreResult _withMidi(ScoreResult r) => ScoreResult(
  scoreId: r.scoreId,
  audioTracks: r.audioTracks,
  scoreImages: r.scoreImages,
  review: r.review,
  tempoBpm: r.tempoBpm,
  midiCombined: MidiCombinedFile(url: Uri.parse('https://cdn.test/c.mid'), fileId: 'f1'),
);

Future<(PlaybackState, PlaybackHarness)> _open(
  ScoreResult result,
  Future<Map<VoicePart, Uri>?> Function() render,
) async {
  SharedPreferences.setMockInitialValues({'onboarding_completed': true});
  final harness = PlaybackHarness(ScriptedScoreResultApi([result]));
  final container = ProviderContainer(
    overrides: [
      ...harness.overrides,
      midiVoiceRendererProvider.overrideWithValue((r, bars) => render()),
    ],
  );
  addTearDown(container.dispose);
  final sub = container.listen(playbackControllerProvider(kScoreId), (_, _) {});
  addTearDown(sub.close);
  for (var i = 0; i < 50; i++) {
    await Future<void>.delayed(const Duration(milliseconds: 10));
    if (sub.read().phase != PlaybackPhase.loading) break;
  }
  return (sub.read(), harness);
}

void main() {
  final wavs = {
    for (final v in VoicePart.values) v: Uri.parse('file:///r/${v.name}.wav'),
  };

  test('no midiCombined -> mp3, renderer not called', () async {
    var called = false;
    final (s, h) = await _open(testResult(), () async {
      called = true;
      return wavs;
    });
    expect(s.phase, PlaybackPhase.ready);
    expect(s.source, PlaybackSource.mp3);
    expect(called, isFalse);
    expect(h.engine.loaded!.values.first.scheme, 'https');
  });

  test('render success -> wav uris loaded', () async {
    final (s, h) = await _open(_withMidi(testResult()), () async => wavs);
    expect(s.source, PlaybackSource.midi);
    expect(h.engine.loaded, wavs);
  });

  test('render returns null -> mp3 fallback', () async {
    final (s, h) = await _open(_withMidi(testResult()), () async => null);
    expect(s.phase, PlaybackPhase.ready);
    expect(s.source, PlaybackSource.mp3);
    expect(h.engine.loaded!.values.first.scheme, 'https');
  });

  test('render throws -> mp3 fallback', () async {
    final (s, _) = await _open(_withMidi(testResult()), () async => throw StateError('x'));
    expect(s.source, PlaybackSource.mp3);
  });
}
