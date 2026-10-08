import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/services/score_result_api.dart';
import 'package:piyanota_application/state/playback_providers.dart';

import 'playback_fakes.dart';

void main() {
  PlaybackHarness ready({Set<VoicePart>? voices, bool review = true}) =>
      PlaybackHarness(
        ScriptedScoreResultApi([
          testResult(
            voices: voices ?? {...VoicePart.values},
            reviewNeeded: review,
          ),
        ], timing: testTiming()),
      );

  Finder chip(VoicePart voice) =>
      find.byKey(ValueKey('voice-chip-${voice.name}'));
  bool chipSelected(WidgetTester tester, VoicePart voice) =>
      tester.widget<FilterChip>(chip(voice)).selected;
  String positionText(WidgetTester tester) =>
      tester.widget<Text>(find.byKey(const ValueKey('time-position'))).data!;
  Rect band(WidgetTester tester) =>
      tester.getRect(find.byKey(const ValueKey('playback-band')));

  Future<void> tapTooltip(WidgetTester tester, String tooltip) async {
    await tester.tap(find.byTooltip(tooltip));
    await tester.pump();
  }

  group('loading and default voice (AC1, AC3)', () {
    testWidgets('shows title, composer, page and all four voices by default', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);

      expect(find.text(kTitle), findsOneWidget);
      expect(find.text(PlaybackMessages.arrangedBy(kComposer)), findsOneWidget);
      expect(find.byKey(const ValueKey('score-scroll')), findsOneWidget);
      for (final voice in VoicePart.values) {
        expect(chipSelected(tester, voice), isTrue, reason: voice.name);
        expect(harness.engine.volumes[voice], 1);
      }
      expect(find.byKey(const ValueKey('time-duration')), findsOneWidget);
      expect(find.text('0:10'), findsOneWidget);
    });

    testWidgets('the onboarding voice is the only one selected', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness, defaultVoice: VoicePart.alto);

      expect(chipSelected(tester, VoicePart.alto), isTrue);
      for (final voice in [
        VoicePart.soprano,
        VoicePart.tenor,
        VoicePart.bass,
      ]) {
        expect(chipSelected(tester, voice), isFalse);
        expect(harness.engine.volumes[voice], 0);
      }
      expect(harness.engine.volumes[VoicePart.alto], 1);
    });

    testWidgets('onboarding voice missing from the score: all available', (
      tester,
    ) async {
      final harness = ready(
        voices: {VoicePart.soprano, VoicePart.alto, VoicePart.bass},
      );
      await pumpPlayback(tester, harness, defaultVoice: VoicePart.tenor);

      expect(chipSelected(tester, VoicePart.soprano), isTrue);
      expect(chipSelected(tester, VoicePart.alto), isTrue);
      expect(chipSelected(tester, VoicePart.bass), isTrue);
      expect(chipSelected(tester, VoicePart.tenor), isFalse);
      // Disabled, not selectable.
      expect(
        tester.widget<FilterChip>(chip(VoicePart.tenor)).onSelected,
        isNull,
      );
    });
  });

  group('voice chips (AC2)', () {
    testWidgets('multi-select toggles audio; the last chip stays on', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness, defaultVoice: VoicePart.soprano);

      await tester.tap(chip(VoicePart.bass));
      await tester.pump();
      expect(chipSelected(tester, VoicePart.bass), isTrue);
      expect(harness.engine.volumes[VoicePart.bass], 1);

      await tester.tap(chip(VoicePart.soprano));
      await tester.pump();
      expect(chipSelected(tester, VoicePart.soprano), isFalse);
      expect(harness.engine.volumes[VoicePart.soprano], 0);

      // Bass is now the only one: refusing keeps it on and says why.
      await tester.tap(chip(VoicePart.bass));
      await tester.pump();
      expect(chipSelected(tester, VoicePart.bass), isTrue);
      expect(harness.engine.volumes[VoicePart.bass], 1);
      // findsWidgets: ScaffoldMessenger also mirrors it onto the library
      // Scaffold underneath.
      expect(find.text(PlaybackMessages.keepOneVoice), findsWidgets);
    });
  });

  group('transport (AC4, AC5)', () {
    testWidgets('play/pause follows the engine', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);

      expect(find.byTooltip(PlaybackMessages.play), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      expect(harness.engine.playing, isTrue);
      expect(find.byTooltip(PlaybackMessages.pause), findsOneWidget);

      await tester.pump(const Duration(milliseconds: 2100));
      expect(positionText(tester), '0:02');

      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      expect(harness.engine.playing, isFalse);
      expect(find.byTooltip(PlaybackMessages.play), findsOneWidget);
    });

    testWidgets('±5 s skips clamp to the track', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);

      await tapTooltip(tester, PlaybackMessages.back5);
      expect(harness.engine.seeks.last, Duration.zero);

      await tapTooltip(tester, PlaybackMessages.forward5);
      expect(harness.engine.seeks.last, const Duration(seconds: 5));
      expect(positionText(tester), '0:05');

      await tapTooltip(tester, PlaybackMessages.forward5);
      await tapTooltip(tester, PlaybackMessages.forward5);
      expect(harness.engine.seeks.last, const Duration(seconds: 10));
      expect(positionText(tester), '0:10');
    });

    testWidgets('⏮ goes to bar 1, ⏭ to the last bar', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);

      await tapTooltip(tester, PlaybackMessages.toLastBar);
      expect(harness.engine.seeks.last, const Duration(milliseconds: 3500));
      await tapTooltip(tester, PlaybackMessages.toStart);
      expect(harness.engine.seeks.last, const Duration(milliseconds: 500));
    });

    testWidgets('dragging the seek bar jumps the audio', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);

      final slider = find.byKey(const ValueKey('seek-bar'));
      final rect = tester.getRect(slider);
      // Material slider has thumb padding; aim near 3/4 of the track.
      await tester.tapAt(Offset(rect.left + rect.width * 0.75, rect.center.dy));
      await tester.pump();
      final landed = harness.engine.seeks.last;
      expect(landed.inMilliseconds, inInclusiveRange(6500, 8500));
      expect(positionText(tester), PlaybackMessages.time(landed));
    });
  });

  group('indicator (AC6, AC7)', () {
    testWidgets('band follows the audio across systems', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);

      final atStart = band(tester);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 1000));
      final playing = band(tester);
      expect(playing.center.dx, greaterThan(atStart.center.dx));
      expect(playing.top, atStart.top);

      // 3.6 s: second system, lower on the page.
      await tester.pump(const Duration(milliseconds: 2600));
      expect(band(tester).top, greaterThan(atStart.bottom));
    });

    testWidgets('a seek moves the band on the next frame (<200 ms)', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);

      final before = band(tester);
      await tapTooltip(tester, PlaybackMessages.toLastBar);
      // One pump, zero elapsed time: well within 200 ms.
      final after = band(tester);
      expect(after.top, greaterThan(before.bottom));
      expect(after, isNot(before));
    });

    testWidgets('band is driven by audio position, so speed needs no change', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      final container = appContainer(tester);
      await container
          .read(playbackControllerProvider(kScoreId).notifier)
          .setSpeed(2);
      expect(harness.engine.speed, 2);

      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 1800));
      // 1.8 s of wall time at 2x is 3.6 s of audio: second system.
      expect(positionText(tester), '0:03');
      final secondSystem = band(tester);
      await tapTooltip(tester, PlaybackMessages.toStart);
      expect(secondSystem.top, greaterThan(band(tester).bottom));
    });
  });

  group('review banner', () {
    testWidgets('shows when review is needed and can be dismissed', (
      tester,
    ) async {
      await pumpPlayback(tester, ready());
      expect(find.byKey(const ValueKey('review-banner')), findsOneWidget);
      await tester.tap(find.byTooltip(PlaybackMessages.dismissReview));
      await tester.pump();
      expect(find.byKey(const ValueKey('review-banner')), findsNothing);
    });

    testWidgets('hidden when the result says no review is needed', (
      tester,
    ) async {
      await pumpPlayback(tester, ready(review: false));
      expect(find.byKey(const ValueKey('review-banner')), findsNothing);
    });
  });

  group('mixer, speed, export (AC8)', () {
    testWidgets('sheets open over playback without pausing it', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();

      for (final (open, title) in [
        (
          find.bySemanticsLabel(PlaybackMessages.voiceMixer),
          PlaybackMessages.mixerSheetTitle,
        ),
        (
          find.bySemanticsLabel(PlaybackMessages.speed),
          PlaybackMessages.speedSheetTitle,
        ),
        (
          find.byTooltip(PlaybackMessages.download),
          PlaybackMessages.exportSheetTitle,
        ),
      ]) {
        await tester.tap(open);
        await settle(tester);
        expect(find.text(PlaybackMessages.comingSoon), findsOneWidget);
        expect(find.text(title), findsWidgets);
        expect(harness.engine.playing, isTrue, reason: title);
        await tester.tap(find.byTooltip(PlaybackMessages.close));
        await settle(tester);
        expect(find.text(PlaybackMessages.comingSoon), findsNothing);
      }
      expect(harness.engine.pauseCalls, 0);
      expect(find.text(kTitle), findsOneWidget);
    });
  });

  group('errors and leaving', () {
    Future<void> expectError(
      WidgetTester tester,
      ScoreResultException error,
      PlaybackError kind,
    ) async {
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([error, testResult()], timing: testTiming()),
      );
      await pumpPlayback(tester, harness);
      final gate = Completer<void>();
      harness.api.gate = gate;
      expect(find.text(PlaybackMessages.errorHeading(kind)), findsOneWidget);
      expect(find.text(PlaybackMessages.errorBody(kind)), findsOneWidget);
      expect(find.byKey(const ValueKey('play-pause')), findsNothing);

      await tester.tap(find.text(PlaybackMessages.retry));
      await tester.pump();
      expect(find.text(PlaybackMessages.loading), findsOneWidget);
      expect(find.text(PlaybackMessages.errorHeading(kind)), findsNothing);
      gate.complete();
      await settle(tester);
      expect(harness.api.fetches, 2);
      expect(find.byKey(const ValueKey('play-pause')), findsOneWidget);
      expect(find.text(PlaybackMessages.errorHeading(kind)), findsNothing);
    }

    testWidgets('409 still converting, then Retry loads', (tester) async {
      await expectError(
        tester,
        const ScoreResultNotReadyException(),
        PlaybackError.notReady,
      );
    });

    testWidgets('404 not found, then Retry loads', (tester) async {
      await expectError(
        tester,
        const ScoreResultNotFoundException(),
        PlaybackError.notFound,
      );
    });

    testWidgets('loading state shows until the result arrives', (tester) async {
      final harness = ready();
      final gate = Completer<void>();
      harness.api.gate = gate;
      await pumpPlayback(tester, harness);
      expect(find.text(PlaybackMessages.loading), findsOneWidget);
      expect(find.text(kTitle), findsOneWidget);
      expect(find.byKey(const ValueKey('play-pause')), findsNothing);
      gate.complete();
      await settle(tester);
      expect(find.text(PlaybackMessages.loading), findsNothing);
      expect(find.byKey(const ValueKey('play-pause')), findsOneWidget);
    });

    testWidgets('audio that will not load is its own state', (tester) async {
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([testResult()], timing: testTiming()),
        engineLoadError: Exception('codec'),
      );
      await pumpPlayback(tester, harness);
      expect(
        find.text(PlaybackMessages.errorHeading(PlaybackError.audio)),
        findsOneWidget,
      );
      expect(harness.engine.disposed, isTrue);
    });

    testWidgets('timing that will not load still plays, without a band', (
      tester,
    ) async {
      final harness = PlaybackHarness(ScriptedScoreResultApi([testResult()]));
      await pumpPlayback(tester, harness);
      expect(find.byKey(const ValueKey('play-pause')), findsOneWidget);
      expect(find.byKey(const ValueKey('playback-band')), findsNothing);
      await tapTooltip(tester, PlaybackMessages.toLastBar);
      expect(harness.engine.seeks.last, const Duration(seconds: 10));
    });

    testWidgets('session expiry goes to Login, clearing the stack', (
      tester,
    ) async {
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([const ScoreResultSessionExpiredException()]),
      );
      await pumpPlayback(tester, harness);
      await settle(tester);
      expect(find.text(kLogin), findsOneWidget);
      expect(harness.secureStorage.values['session_token'], isNull);
    });

    testWidgets('back pauses, returns to the library, releases audio', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();

      await tester.tap(find.byTooltip(PlaybackMessages.back));
      await settle(tester);
      expect(find.text(kLibrary), findsOneWidget);
      expect(harness.engine.pauseCalls, greaterThan(0));
      // The provider is released once the popped route is gone.
      await tester.pump(const Duration(seconds: 1));
      expect(harness.engine.disposed, isTrue);
    });

    testWidgets('backgrounding the app pauses', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      await tester.pump();
      expect(harness.engine.playing, isFalse);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    });
  });

  group('layout', () {
    for (final (name, size, scale) in [
      ('360 dp', const Size(360, 640), 1.0),
      ('360 dp at 1.3x text', const Size(360, 740), 1.3),
      ('412 dp at 2x text', const Size(412, 917), 2.0),
    ]) {
      testWidgets('fits without overflow: $name', (tester) async {
        await pumpPlayback(tester, ready(), size: size, textScale: scale);
        expect(tester.takeException(), isNull);
        for (final key in ['play-pause', 'seek-bar', 'time-duration']) {
          expect(find.byKey(ValueKey(key)), findsOneWidget);
        }
        // Touch targets (≥ 48 dp) on the transport row.
        for (final tooltip in [
          PlaybackMessages.toStart,
          PlaybackMessages.back5,
          PlaybackMessages.forward5,
          PlaybackMessages.toLastBar,
        ]) {
          final rect = tester.getRect(
            find
                .ancestor(
                  of: find.byTooltip(tooltip),
                  matching: find.byType(IconButton),
                )
                .first,
          );
          expect(rect.width, greaterThanOrEqualTo(48), reason: tooltip);
          expect(rect.height, greaterThanOrEqualTo(48), reason: tooltip);
        }
      });
    }
  });

  group('accessibility guidelines', () {
    testWidgets('ready state', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpPlayback(tester, ready());
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      handle.dispose();
    });

    testWidgets('error state', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpPlayback(
        tester,
        PlaybackHarness(
          ScriptedScoreResultApi([const ScoreResultNotReadyException()]),
        ),
      );
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      handle.dispose();
    });
  });
}
