import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/state/playback_providers.dart';

import 'playback_fakes.dart';

PlaybackHarness _harness() => PlaybackHarness(
  ScriptedScoreResultApi([testResult(), testResult()], timing: testTiming()),
);

final _notice = find.byKey(const ValueKey('accuracy-notice'));

Future<void> _leaveAndReopen(WidgetTester tester) async {
  await tester.tap(find.byTooltip(PlaybackMessages.back));
  await settle(tester);
  await tester.pump(const Duration(seconds: 1));
  await reopenPlayback(tester);
}

void main() {
  testWidgets('disclaimer shows once per score, not after reopening', (
    tester,
  ) async {
    await pumpPlayback(tester, _harness());
    expect(_notice, findsOneWidget);
    await _leaveAndReopen(tester);
    expect(_notice, findsNothing);
  });

  testWidgets('a saved seen flag keeps the disclaimer away (app restart)', (
    tester,
  ) async {
    await pumpPlayback(
      tester,
      _harness(),
      prefs: {PlaybackPrefs.disclaimerKey(kScoreId): true},
    );
    expect(_notice, findsNothing);
  });

  testWidgets('mixer and speed are saved and restored into the engine', (
    tester,
  ) async {
    final harness = _harness();
    await pumpPlayback(tester, harness);
    final c = appContainer(tester)
        .read(playbackControllerProvider(kScoreId).notifier);
    c.setVoiceVolume(VoicePart.alto, 0.3);
    c.setMetronomeOn(on: true);
    c.setBpm(60);
    c.commitBpm();
    await tester.pump();
    await _leaveAndReopen(tester);

    final state = appContainer(tester)
        .read(playbackControllerProvider(kScoreId));
    expect(state.volumes[VoicePart.alto], 0.3);
    expect(state.metronomeOn, isTrue);
    expect(state.chosenBpm, 60);
    // Reached the engine, not only the state.
    expect(harness.engine.volumes[VoicePart.alto], 0.3);
    expect(harness.engine.speed, closeTo(60 / state.tempoBpm, 1e-9));
  });

  testWidgets('restored muted voice is audible once its chip is turned on', (
    tester,
  ) async {
    final harness = _harness();
    await pumpPlayback(
      tester,
      harness,
      prefs: {
        PlaybackPrefs.mixKey(kScoreId): jsonEncode({
          'selected': ['soprano'],
          'muted': ['alto'],
        }),
      },
    );
    final container = appContainer(tester);
    final c = container.read(playbackControllerProvider(kScoreId).notifier);
    expect(container.read(playbackControllerProvider(kScoreId)).muted, {
      VoicePart.alto,
    });
    c.toggleVoice(VoicePart.alto);
    await tester.pump();
    expect(container.read(playbackControllerProvider(kScoreId)).muted, isEmpty);
    expect(harness.engine.volumes[VoicePart.alto], greaterThan(0));
  });

  testWidgets(
    'saved mutes are ignored when no saved selected voice is playable',
    (tester) async {
      final voices = {VoicePart.alto, VoicePart.bass};
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([
          testResult(voices: voices),
          testResult(voices: voices),
        ], timing: testTiming()),
      );
      await pumpPlayback(
        tester,
        harness,
        prefs: {
          PlaybackPrefs.mixKey(kScoreId): jsonEncode({
            'selected': ['soprano'],
            'muted': ['alto'],
          }),
        },
      );
      final state = appContainer(tester)
          .read(playbackControllerProvider(kScoreId));
      expect(state.muted, isNot(contains(VoicePart.alto)));
      expect(state.muted, state.muted.difference(state.selected));
    },
  );
}
