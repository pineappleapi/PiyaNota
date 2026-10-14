import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/voice_failure.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/screens/retake/rephotograph.dart';

import 'playback_fakes.dart';

const _three = {VoicePart.soprano, VoicePart.alto, VoicePart.bass};

PlaybackHarness _harness(VoiceFailureCause tenorCause) => PlaybackHarness(
  ScriptedScoreResultApi([
    testResult(
      voices: _three,
      failedVoices: {VoicePart.tenor},
      failedVoiceCauses: {VoicePart.tenor: tenorCause},
    ),
  ], timing: testTiming()),
);

final _offer = find.byKey(const Key('rephotograph-offer'));
final _unreadableAlert = find.byKey(const Key('unreadable-voice-alert'));
final _failedAlert = find.byKey(const ValueKey('failed-voices-alert'));
final _tenorChip = find.byKey(const ValueKey('voice-chip-tap-tenor'));
final _retakeMarker = find.text('ROUTE:whole-retake $kJobId $kTitle 90 42');

/// The answered pref for [kJobId], so the AC11 offer is out of the way.
const _answered = {'rephotograph_offer_answered_$kJobId': true};

void main() {
  group('PIYA-207 AC11 when opened from the library', () {
    testWidgets('unreadable: the offer, once per job', (tester) async {
      await pumpPlayback(tester, _harness(VoiceFailureCause.unreadable));
      expect(_offer, findsOneWidget);
      expect(find.text('Continue with 3 voices'), findsOneWidget);
      // The unreadable voice isn't in the PIYA-208 failed-voice alert.
      expect(_failedAlert, findsNothing);
      await tester.tap(find.text('Continue with 3 voices'));
      await settle(tester);
      expect(_offer, findsNothing);
      expect(await RephotographOfferPrefs.isAnswered(kJobId), isTrue);

      await tester.binding.handlePopRoute();
      await settle(tester);
      await reopenPlayback(tester);
      expect(_offer, findsNothing);
    });

    testWidgets('system Back: library, offered again next time', (
      tester,
    ) async {
      await pumpPlayback(tester, _harness(VoiceFailureCause.unreadable));
      expect(_offer, findsOneWidget);
      await tester.binding.handlePopRoute();
      await settle(tester);
      await settle(tester);
      expect(find.text(kLibrary), findsOneWidget);
      expect(await RephotographOfferPrefs.isAnswered(kJobId), isFalse);
      await reopenPlayback(tester);
      expect(_offer, findsOneWidget);
    });

    testWidgets('Re-photograph: Capture for this job, pre-filled', (
      tester,
    ) async {
      await pumpPlayback(tester, _harness(VoiceFailureCause.unreadable));
      await tester.tap(find.text(RephotographMessages.rephotograph));
      await settle(tester);
      await settle(tester);
      expect(_retakeMarker, findsOneWidget);
    });

    testWidgets('render_failed: no offer, the failed-voice alert', (
      tester,
    ) async {
      await pumpPlayback(tester, _harness(VoiceFailureCause.renderFailed));
      expect(_offer, findsNothing);
      expect(_failedAlert, findsOneWidget);
      expect(
        find.text(PlaybackMessages.failedVoicesBody([VoicePart.tenor], 3)),
        findsOneWidget,
      );
    });
  });

  group('PIYA-208 unreadable chip', () {
    testWidgets('tap: "<Voice> couldn\'t be read", Cancel stays', (
      tester,
    ) async {
      await pumpPlayback(
        tester,
        _harness(VoiceFailureCause.unreadable),
        prefs: _answered,
      );
      expect(_offer, findsNothing);
      await tester.tap(_tenorChip);
      await settle(tester);
      expect(_unreadableAlert, findsOneWidget);
      expect(
        find.text(RephotographMessages.unreadableTitle(VoicePart.tenor)),
        findsOneWidget,
      );
      await tester.tap(find.text(RephotographMessages.cancel));
      await settle(tester);
      expect(_unreadableAlert, findsNothing);
      expect(_retakeMarker, findsNothing);
    });

    testWidgets('Re-photograph goes to Capture', (tester) async {
      await pumpPlayback(
        tester,
        _harness(VoiceFailureCause.unreadable),
        prefs: _answered,
      );
      await tester.tap(_tenorChip);
      await settle(tester);
      await tester.tap(find.text(RephotographMessages.rephotograph));
      await settle(tester);
      await settle(tester);
      expect(_retakeMarker, findsOneWidget);
    });

    testWidgets('a render_failed chip has no tap', (tester) async {
      await pumpPlayback(tester, _harness(VoiceFailureCause.renderFailed));
      await tester.tap(find.text(PlaybackMessages.ok));
      await settle(tester);
      expect(_tenorChip, findsNothing);
    });
  });

  testWidgets('PIYA-209 unreadable Mixer row: alert, closes Mixer, Capture', (
    tester,
  ) async {
    await pumpPlayback(
      tester,
      _harness(VoiceFailureCause.unreadable),
      prefs: _answered,
    );
    await tester.tap(find.bySemanticsLabel(PlaybackMessages.voiceMixer));
    await settle(tester);
    await tester.tap(find.byKey(const ValueKey('mixer-row-tenor')));
    await settle(tester);
    expect(_unreadableAlert, findsOneWidget);
    await tester.tap(find.text(RephotographMessages.rephotograph));
    await settle(tester);
    await settle(tester);
    expect(find.byKey(const ValueKey('mixer-sheet')), findsNothing);
    expect(_retakeMarker, findsOneWidget);
  });
}
