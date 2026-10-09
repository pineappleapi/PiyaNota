import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/screens/playback/playback_screen.dart';
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
    testWidgets('shows title, arranger, page and all four voices by default', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);

      expect(find.text(kTitle), findsOneWidget);
      expect(find.text(PlaybackMessages.arrangedBy(kArranger)), findsOneWidget);
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

    testWidgets('the end of the track resets to Play; Play restarts', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await tester.pump(const Duration(seconds: 11));
      await tester.pump();
      expect(harness.engine.playing, isFalse);
      expect(find.byTooltip(PlaybackMessages.play), findsOneWidget);
      expect(positionText(tester), '0:10');

      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 1100));
      expect(harness.engine.playing, isTrue);
      expect(positionText(tester), '0:01');
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

    testWidgets('a held seek-bar drag moves the band before any seek lands', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      final gate = Completer<void>();
      harness.engine.seekGate = gate;

      final before = band(tester);
      final rect = tester.getRect(find.byKey(const ValueKey('seek-bar')));
      final drag = await tester.startGesture(
        Offset(rect.left + rect.width * 0.1, rect.center.dy),
      );
      await drag.moveTo(Offset(rect.left + rect.width * 0.8, rect.center.dy));
      // One frame, no time passed, finger still down, no seek issued yet.
      await tester.pump();
      expect(harness.engine.seeks, isEmpty);
      expect(band(tester).top, greaterThan(before.bottom));

      // Released: the seek is issued but held; the band stays put.
      await drag.up();
      await tester.pump();
      expect(harness.engine.seeks, hasLength(1));
      final held = band(tester);
      expect(held.top, greaterThan(before.bottom));
      gate.complete();
      await tester.pump();
      expect(band(tester), held);
    });

    testWidgets('an earlier seek landing does not end a newer drag', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      final gate = Completer<void>();
      harness.engine.seekGate = gate;
      final rect = tester.getRect(find.byKey(const ValueKey('seek-bar')));
      Offset at(double fraction) =>
          Offset(rect.left + rect.width * fraction, rect.center.dy);

      // First drag released: its seek is held in flight.
      await tester.dragFrom(at(0.1), at(0.8) - at(0.1));
      await tester.pump();
      expect(harness.engine.seeks, hasLength(1));

      // A second drag starts and is still held when the first seek lands.
      final drag = await tester.startGesture(at(0.5));
      await drag.moveTo(at(0.3));
      await tester.pump();
      final dragging = positionText(tester);
      gate.complete();
      await tester.pump();
      await tester.pump();
      expect(positionText(tester), dragging);

      await drag.up();
      await tester.pump();
      expect(harness.engine.seeks, hasLength(2));
      expect(positionText(tester), dragging);
    });

    testWidgets('a failed seek does not freeze the seek bar or band', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      harness.engine.seekError = StateError('seek failed');

      final rect = tester.getRect(find.byKey(const ValueKey('seek-bar')));
      await tester.tapAt(Offset(rect.left + rect.width * 0.75, rect.center.dy));
      await tester.pump();
      // The seek never landed, so the display goes back to the audio.
      expect(positionText(tester), '0:00');

      harness.engine.seekError = null;
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 2100));
      expect(positionText(tester), '0:02');
      expect(tester.takeException(), isNull);
    });

    testWidgets('band is driven by audio position, so speed needs no change', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      final container = appContainer(tester);
      container.read(playbackControllerProvider(kScoreId).notifier).setBpm(180);
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
    testWidgets('the export sheet opens over playback without pausing it', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();

      for (final (open, title) in [
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

    testWidgets('404 not found offers only Back to library', (tester) async {
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([const ScoreResultNotFoundException()]),
      );
      await pumpPlayback(tester, harness);
      expect(
        find.text(PlaybackMessages.errorHeading(PlaybackError.notFound)),
        findsOneWidget,
      );
      // Asking again can't bring a deleted score back.
      expect(find.text(PlaybackMessages.retry), findsNothing);
      await tester.tap(find.text(PlaybackMessages.backToLibrary));
      await settle(tester);
      expect(find.text(kLibrary), findsOneWidget);
      expect(harness.api.fetches, 1);
    });

    testWidgets('an untyped load failure is the server error, not a spinner', (
      tester,
    ) async {
      // Not a ScoreResultException: the scripted API throws a plain
      // Exception, standing in for a misconfigured provider's StateError or
      // an unreadable token's PlatformException.
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([Exception('not a result')]),
      );
      await pumpPlayback(tester, harness);
      expect(find.text(PlaybackMessages.loading), findsNothing);
      expect(
        find.text(PlaybackMessages.errorHeading(PlaybackError.server)),
        findsOneWidget,
      );
    });

    testWidgets('an engine that throws on creation is the audio error', (
      tester,
    ) async {
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([testResult()], timing: testTiming()),
        engineCreateError: StateError('no audio plugin'),
      );
      await pumpPlayback(tester, harness);
      expect(find.text(PlaybackMessages.loading), findsNothing);
      expect(
        find.text(PlaybackMessages.errorHeading(PlaybackError.audio)),
        findsOneWidget,
      );
    });

    testWidgets('one voice failing to load: the rest play, its chip is off', (
      tester,
    ) async {
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([testResult()], timing: testTiming()),
        engineFailAtLoad: {VoicePart.tenor},
      );
      await pumpPlayback(tester, harness);
      expect(find.byKey(const ValueKey('play-pause')), findsOneWidget);
      expect(
        find.text(PlaybackMessages.audioUnavailable([VoicePart.tenor])),
        findsWidgets,
      );
      expect(
        tester.widget<FilterChip>(chip(VoicePart.tenor)).onSelected,
        isNull,
      );
      expect(chipSelected(tester, VoicePart.tenor), isFalse);
      for (final voice in [VoicePart.soprano, VoicePart.alto, VoicePart.bass]) {
        expect(chipSelected(tester, voice), isTrue, reason: voice.name);
      }

      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      expect(harness.engine.playing, isTrue);
    });

    testWidgets('the default voice failing to load selects the others', (
      tester,
    ) async {
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([testResult()], timing: testTiming()),
        engineFailAtLoad: {VoicePart.alto},
      );
      await pumpPlayback(tester, harness, defaultVoice: VoicePart.alto);
      expect(find.byKey(const ValueKey('play-pause')), findsOneWidget);
      expect(chipSelected(tester, VoicePart.alto), isFalse);
      for (final voice in [
        VoicePart.soprano,
        VoicePart.tenor,
        VoicePart.bass,
      ]) {
        expect(chipSelected(tester, voice), isTrue, reason: voice.name);
      }
    });

    testWidgets('every voice failing to load is the audio error', (
      tester,
    ) async {
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([testResult()], timing: testTiming()),
        engineFailAtLoad: {...VoicePart.values},
      );
      await pumpPlayback(tester, harness);
      expect(
        find.text(PlaybackMessages.errorHeading(PlaybackError.audio)),
        findsOneWidget,
      );
      expect(harness.engine.disposed, isTrue);
    });

    testWidgets('a voice dropping out mid-play: the others keep playing', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      final engine = harness.engine;

      engine.fail(VoicePart.alto);
      await tester.pump();
      await tester.pump();
      expect(find.byKey(const ValueKey('play-pause')), findsOneWidget);
      expect(engine.playing, isTrue);
      expect(engine.disposed, isFalse);
      expect(
        find.text(PlaybackMessages.audioUnavailable([VoicePart.alto])),
        findsWidgets,
      );
      expect(
        tester.widget<FilterChip>(chip(VoicePart.alto)).onSelected,
        isNull,
      );
      expect(chipSelected(tester, VoicePart.alto), isFalse);

      // The failed chip can't be chosen again.
      await tester.tap(chip(VoicePart.alto), warnIfMissed: false);
      await tester.pump();
      expect(chipSelected(tester, VoicePart.alto), isFalse);
      expect(engine.playing, isTrue);
    });

    testWidgets('the only selected voice dropping out selects the rest', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness, defaultVoice: VoicePart.bass);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();

      // The bass was also the master: the engine moved the clock to
      // another track (see the engine tests), so this is not fatal.
      harness.engine.fail(VoicePart.bass);
      await tester.pump();
      await tester.pump();
      expect(harness.engine.playing, isTrue);
      expect(chipSelected(tester, VoicePart.bass), isFalse);
      for (final voice in [
        VoicePart.soprano,
        VoicePart.alto,
        VoicePart.tenor,
      ]) {
        expect(chipSelected(tester, voice), isTrue, reason: voice.name);
        expect(harness.engine.volumes[voice], 1, reason: voice.name);
      }

      // Still at least one voice: the last one stays on.
      await tester.tap(chip(VoicePart.alto));
      await tester.tap(chip(VoicePart.tenor));
      await tester.pump();
      await tester.tap(chip(VoicePart.soprano));
      await tester.pump();
      expect(chipSelected(tester, VoicePart.soprano), isTrue);
    });

    testWidgets('the last playable voice failing stops on the audio error', (
      tester,
    ) async {
      final harness = PlaybackHarness(
        ScriptedScoreResultApi([testResult()], timing: testTiming()),
        engineFailAtLoad: {VoicePart.soprano, VoicePart.alto, VoicePart.tenor},
      );
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      final engine = harness.engine;

      engine.fail(VoicePart.bass, fatal: true);
      await tester.pump();
      await tester.pump();
      expect(
        find.text(PlaybackMessages.errorHeading(PlaybackError.audio)),
        findsOneWidget,
      );
      expect(find.byKey(const ValueKey('play-pause')), findsNothing);
      expect(engine.playing, isFalse);
      expect(engine.disposed, isTrue);

      // Retry builds a fresh engine.
      await tester.tap(find.text(PlaybackMessages.retry));
      await settle(tester);
      expect(harness.engines, hasLength(2));
      expect(find.byKey(const ValueKey('play-pause')), findsOneWidget);
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
      expect(find.text(PlaybackMessages.indicatorUnavailable), findsOneWidget);
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

  test('page images: file only in the demo build', () {
    final file = Uri.parse('file:///data/p1.png');
    expect(scoreImageFor(file, allowLocalFiles: false), isNull);
    expect(scoreImageFor(file, allowLocalFiles: true), isA<FileImage>());
    expect(
      scoreImageFor(Uri.parse('https://cdn/p1.png'), allowLocalFiles: false),
      isA<NetworkImage>(),
    );
    expect(
      scoreImageFor(Uri.parse('content://x/p1'), allowLocalFiles: true),
      isNull,
    );
  });

  group('timing pages', () {
    test('events on pages the result has no image for are dropped', () {
      // Page 1's URL was rejected (a null slot); page 3 doesn't exist.
      final result = ScoreResult(
        scoreId: kScoreId,
        audioTracks: {VoicePart.soprano: Uri.parse('https://cdn.test/s.mp3')},
        scoreImages: [Uri.parse('test://p0'), null, Uri.parse('test://p2')],
        review: const ReviewSummary(reviewNeeded: false),
      );
      final kept = PlaybackController.onExistingPages([
        ev(0, 10, 10),
        ev(100, 10, 10, page: 1),
        ev(200, 10, 10, page: -1),
        ev(300, 10, 10, page: 2),
        ev(400, 10, 10, page: 3),
      ], result.hasPage);
      expect(kept.map((e) => e.timestampMs), [0, 300]);
    });

    testWidgets('an out-of-range page in the timing does not break the band', (
      tester,
    ) async {
      final harness = PlaybackHarness(
        ScriptedScoreResultApi(
          [testResult()],
          timing: [...testTiming(), ev(6000, 100, 100, bar: 4, page: 3)],
        ),
      );
      await pumpPlayback(tester, harness);
      await tapTooltip(tester, PlaybackMessages.forward5);
      await tapTooltip(tester, PlaybackMessages.forward5);
      expect(tester.takeException(), isNull);
      expect(find.byKey(const ValueKey('playback-band')), findsOneWidget);
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
