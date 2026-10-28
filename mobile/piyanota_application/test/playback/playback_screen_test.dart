import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/screens/playback/playback_screen.dart';
import 'package:piyanota_application/services/score_result_api.dart';
import 'package:piyanota_application/state/playback_providers.dart';
import 'package:piyanota_application/theme/app_theme.dart';

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

  group('time labels under the seek bar ends (PIYA-208-V2.1)', () {
    testWidgets(
      'the seek bar keeps a 48 dp hit box; a tap below the track seeks',
      (tester) async {
        final harness = ready();
        await pumpPlayback(tester, harness);
        final rect = tester.getRect(find.byKey(const ValueKey('seek-bar')));
        expect(rect.height, greaterThanOrEqualTo(48));
        // 20 dp below the track centre: where the time labels now sit.
        await tester.tapAt(
          Offset(rect.left + rect.width * 0.75, rect.center.dy + 20),
        );
        await tester.pump();
        expect(harness.engine.seeks, hasLength(1));
      },
    );

    testWidgets('each time sits under its track end, a small gap below', (
      tester,
    ) async {
      await pumpPlayback(tester, ready());
      final bar = find.byKey(const ValueKey('seek-bar'));
      final box = tester.renderObject<RenderBox>(bar);
      final theme = SliderTheme.of(tester.element(bar));
      // The painted track, not the widget box: Slider insets the track.
      final origin = box.localToGlobal(Offset.zero);
      final track = theme.trackShape!.getPreferredRect(
        parentBox: box,
        offset: origin,
        sliderTheme: theme,
        isEnabled: true,
        isDiscrete: false,
      );
      final position = tester.getRect(
        find.byKey(const ValueKey('time-position')),
      );
      final total = tester.getRect(find.byKey(const ValueKey('time-duration')));

      expect(position.left, closeTo(track.left, 0.5));
      expect(total.right, closeTo(track.right, 0.5));
      // Mockup: track bottom to digit top is 14 dp (412 px = 412 dp, scale
      // 1); minus ~5 dp of line leading, the text box starts 9 dp below.
      expect(position.top - track.bottom, closeTo(9, 0.5));
      expect(total.top - track.bottom, closeTo(9, 0.5));
    });
  });

  group('seek-bar drag is silent, then resumes (PIYA-208-V2.2)', () {
    Future<(PlaybackHarness, TestGesture)> dragging(
      WidgetTester tester, {
      required bool playing,
    }) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      if (playing) {
        await tester.tap(find.byKey(const ValueKey('play-pause')));
        await tester.pump();
        expect(harness.engine.playing, isTrue);
      }
      final rect = tester.getRect(find.byKey(const ValueKey('seek-bar')));
      final gesture = await tester.startGesture(
        Offset(rect.left + rect.width * 0.1, rect.center.dy),
      );
      // Several ticks: only the first may pause.
      for (final f in [0.3, 0.5, 0.8]) {
        await gesture.moveTo(
          Offset(rect.left + rect.width * f, rect.center.dy),
        );
        await tester.pump();
      }
      return (harness, gesture);
    }

    testWidgets('a drag while playing pauses once, with no seek yet', (
      tester,
    ) async {
      final (harness, gesture) = await dragging(tester, playing: true);
      expect(harness.engine.playing, isFalse);
      expect(harness.engine.pauseCalls, 1);
      expect(harness.engine.seeks, isEmpty);
      await gesture.up();
      await tester.pump();
    });

    testWidgets('release seeks, then plays again from the new position', (
      tester,
    ) async {
      final (harness, gesture) = await dragging(tester, playing: true);
      final gate = Completer<void>();
      harness.engine.seekGate = gate;
      final playsBefore = harness.engine.playCalls;
      await gesture.up();
      await tester.pump();
      // Seek issued, not landed: no play before it.
      expect(harness.engine.seeks, hasLength(1));
      expect(harness.engine.playCalls, playsBefore);
      gate.complete();
      await tester.pump();
      await tester.pump();
      expect(harness.engine.playCalls, playsBefore + 1);
      expect(harness.engine.playing, isTrue);
      expect(
        harness.engine.position.inMilliseconds,
        closeTo(harness.engine.seeks.single.inMilliseconds, 100),
      );
    });

    testWidgets('a drag while paused stays paused', (tester) async {
      final (harness, gesture) = await dragging(tester, playing: false);
      await gesture.up();
      await tester.pump();
      await tester.pump();
      expect(harness.engine.seeks, hasLength(1));
      expect(harness.engine.pauseCalls, 0);
      expect(harness.engine.playCalls, 0);
      expect(harness.engine.playing, isFalse);
    });

    testWidgets('a failed seek still ends the drag and resumes', (
      tester,
    ) async {
      final (harness, gesture) = await dragging(tester, playing: true);
      harness.engine.seekError = StateError('seek failed');
      await gesture.up();
      await tester.pump();
      await tester.pump();
      expect(harness.engine.playing, isTrue);
      expect(
        positionText(tester),
        PlaybackMessages.time(harness.engine.position),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('a release at the very end does not restart from 0', (
      tester,
    ) async {
      final (harness, gesture) = await dragging(tester, playing: true);
      final rect = tester.getRect(find.byKey(const ValueKey('seek-bar')));
      await gesture.moveTo(Offset(rect.right + 40, rect.center.dy));
      await tester.pump();
      final playsBefore = harness.engine.playCalls;
      await gesture.up();
      await tester.pump();
      await tester.pump();
      expect(harness.engine.seeks.last, harness.engine.duration);
      expect(harness.engine.playCalls, playsBefore);
      expect(harness.engine.playing, isFalse);
    });

    testWidgets('an app pause while the seek is pending keeps audio paused', (
      tester,
    ) async {
      final (harness, gesture) = await dragging(tester, playing: true);
      final gate = Completer<void>();
      harness.engine.seekGate = gate;
      await gesture.up();
      await tester.pump();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      gate.complete();
      await tester.pump();
      await tester.pump();
      expect(harness.engine.playing, isFalse);
    });

    testWidgets(
      'play tapped mid-drag stays silent and is honoured on release',
      (tester) async {
        final (harness, gesture) = await dragging(tester, playing: false);
        await tester.tap(find.byKey(const ValueKey('play-pause')));
        await tester.pump();
        expect(harness.engine.playing, isFalse);
        await gesture.up();
        await tester.pump();
        await tester.pump();
        expect(harness.engine.playing, isTrue);
      },
    );

    testWidgets('pause tapped mid-drag keeps it paused on release', (
      tester,
    ) async {
      final (harness, gesture) = await dragging(tester, playing: true);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await gesture.up();
      await tester.pump();
      await tester.pump();
      expect(harness.engine.playing, isFalse);
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

      await tester.tap(find.byTooltip(PlaybackMessages.download));
      await settle(tester);
      expect(find.byKey(const ValueKey('export-sheet')), findsOneWidget);
      expect(harness.engine.playing, isTrue);
      await tester.tap(find.byTooltip(PlaybackMessages.close));
      await settle(tester);
      expect(find.byKey(const ValueKey('export-sheet')), findsNothing);
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
      expect(find.byKey(const ValueKey('failed-voices-alert')), findsOneWidget);
      expect(
        find.text(PlaybackMessages.failedVoicesTitle([VoicePart.tenor])),
        findsOneWidget,
      );
      expect(
        find.text(PlaybackMessages.failedVoicesBody([VoicePart.tenor], 3)),
        findsOneWidget,
      );
      await tester.tap(find.text(PlaybackMessages.ok));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('failed-voices-alert')), findsNothing);
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
        find.text(PlaybackMessages.failedVoicesTitle([VoicePart.alto])),
        findsOneWidget,
      );
      await tester.tap(find.text(PlaybackMessages.ok));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
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
      // Item 7: the same failed-voice alert as at load.
      expect(
        find.text(PlaybackMessages.failedVoicesTitle([VoicePart.bass])),
        findsOneWidget,
      );
      await tester.tap(find.text(PlaybackMessages.ok));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
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

  group('zoom and the page stack (PIYA-208-V2.3, V2.4)', () {
    // Short enough that one page doesn't fit, so the stack must scroll.
    const small = Size(412, 700);
    final viewer = find.byKey(const ValueKey('score-scroll'));
    Matrix4 matrix(WidgetTester tester) => tester
        .widget<InteractiveViewer>(viewer)
        .transformationController!
        .value;
    double scale(WidgetTester tester) => matrix(tester).getMaxScaleOnAxis();
    Offset shift(WidgetTester tester) {
      final t = matrix(tester).getTranslation();
      return Offset(t.x, t.y);
    }

    Rect page(WidgetTester tester, int i) =>
        tester.getRect(find.byKey(ValueKey('score-page-$i')));

    /// Wholly on screen; a band taller than the zoomed view counts once
    /// its top is.
    bool inView(WidgetTester tester, Rect rect) {
      final view = tester.getRect(viewer);
      return rect.top >= view.top - 0.5 &&
          rect.top < view.bottom &&
          (rect.bottom <= view.bottom + 0.5 || rect.height > view.height) &&
          rect.left >= view.left - 0.5 &&
          rect.right <= view.right + 0.5;
    }

    PlaybackHarness paged() => PlaybackHarness(
      ScriptedScoreResultApi([
        testResult(pages: 3, reviewNeeded: false),
      ], timing: pagedTiming(3)),
    );

    Future<void> pinch(WidgetTester tester, double from, double to) async {
      final c = tester.getCenter(viewer);
      final a = await tester.startGesture(c - Offset(from, 0), pointer: 1);
      final b = await tester.startGesture(c + Offset(from, 0), pointer: 2);
      await tester.pump();
      for (var i = 1; i <= 10; i++) {
        final d = from + (to - from) * i / 10;
        await a.moveTo(c - Offset(d, 0));
        await b.moveTo(c + Offset(d, 0));
        await tester.pump(const Duration(milliseconds: 16));
      }
      // Held still before lifting: no fling afterwards.
      await tester.pump(const Duration(milliseconds: 200));
      await a.up();
      await b.up();
      await tester.pump();
    }

    /// Spreads two fingers until the scale reaches [target]. Not a fixed
    /// path: the recognizer measures the pinch only from where it passes
    /// its slop, as on a phone.
    Future<void> pinchTo(WidgetTester tester, double target) async {
      final c = tester.getCenter(viewer);
      var d = 40.0;
      final a = await tester.startGesture(c - Offset(d, 0), pointer: 1);
      final b = await tester.startGesture(c + Offset(d, 0), pointer: 2);
      await tester.pump();
      while (scale(tester) < target - 0.01 && d < 400) {
        d += 1;
        await a.moveTo(c - Offset(d, 0));
        await b.moveTo(c + Offset(d, 0));
        await tester.pump(const Duration(milliseconds: 16));
      }
      await tester.pump(const Duration(milliseconds: 200));
      await a.up();
      await b.up();
      await tester.pump();
    }

    Future<void> drag(WidgetTester tester, Offset by) async {
      final g = await tester.startGesture(tester.getCenter(viewer));
      for (var i = 1; i <= 10; i++) {
        await g.moveBy(by / 10);
        await tester.pump(const Duration(milliseconds: 16));
      }
      await tester.pump(const Duration(milliseconds: 200));
      await g.up();
      await tester.pump();
    }

    Future<void> doubleTap(WidgetTester tester) async {
      await tester.tap(viewer);
      await tester.pump(kDoubleTapMinTime);
      await tester.tap(viewer);
      // Lets the second tap's own min-time timer run out.
      await tester.pump(kDoubleTapMinTime);
    }

    /// Frame by frame, as on a phone: one long pump is a single frame, in
    /// which the band can move on while a follow is still finishing.
    Future<void> settleFollow(WidgetTester tester) async {
      for (var i = 0; i < 25; i++) {
        await tester.pump(const Duration(milliseconds: 16));
      }
    }

    testWidgets('pinch to 2x, then the scale is 2', (tester) async {
      await pumpPlayback(tester, paged(), size: small);
      expect(scale(tester), 1);
      await pinchTo(tester, 2);
      expect(scale(tester), closeTo(2, 0.05));
    });

    testWidgets('scale stays clamped to 1-4', (tester) async {
      await pumpPlayback(tester, paged(), size: small);
      await pinch(tester, 20, 200);
      expect(scale(tester), closeTo(4, 0.001));
      await pinch(tester, 200, 10);
      expect(scale(tester), closeTo(1, 0.001));
    });

    testWidgets('the band scales with the page at any zoom (V2.3 AC2)', (
      tester,
    ) async {
      await pumpPlayback(tester, ready(review: false));
      final before = band(tester);
      final pageBefore = page(tester, 0);
      await pinchTo(tester, 2);
      final after = band(tester);
      final pageAfter = page(tester, 0);
      expect(pageAfter.width / pageBefore.width, closeTo(2, 0.02));
      // Same spot and size on the page, as fractions of the page.
      Rect onPage(Rect band, Rect page) => Rect.fromLTRB(
        (band.left - page.left) / page.width,
        (band.top - page.top) / page.height,
        (band.right - page.left) / page.width,
        (band.bottom - page.top) / page.height,
      );
      final was = onPage(before, pageBefore);
      final now = onPage(after, pageAfter);
      for (final (a, b) in [
        (now.left, was.left),
        (now.top, was.top),
        (now.right, was.right),
        (now.bottom, was.bottom),
      ]) {
        expect(a, closeTo(b, 0.001));
      }
    });

    testWidgets('a double-tap resets to 1x', (tester) async {
      await pumpPlayback(tester, paged(), size: small);
      await pinchTo(tester, 2.4);
      expect(scale(tester), greaterThan(2));
      await doubleTap(tester);
      expect(scale(tester), 1);
      expect(shift(tester).dx, 0);
      // Still inside the stack, the bottom page edge not above the view's.
      final view = tester.getRect(viewer);
      expect(shift(tester).dy, lessThanOrEqualTo(0));
      expect(page(tester, 2).bottom + 16, greaterThan(view.bottom - 0.5));
    });

    testWidgets('a drag past either end stays inside the stack', (
      tester,
    ) async {
      await pumpPlayback(tester, paged(), size: small);
      await pinchTo(tester, 2);
      await drag(tester, const Offset(0, 3000));
      expect(shift(tester).dy, 0);
      for (var i = 0; i < 12; i++) {
        await drag(tester, const Offset(0, -600));
      }
      final view = tester.getRect(viewer);
      // At the bottom: the last page's padding ends on the view's edge.
      expect(page(tester, 2).bottom + 16 * 2, closeTo(view.bottom, 0.5));
    });

    testWidgets('a taller screen after scrolling to the bottom leaves no gap', (
      tester,
    ) async {
      await pumpPlayback(tester, paged(), size: small);
      for (var i = 0; i < 8; i++) {
        await drag(tester, const Offset(0, -600));
      }
      tester.view.physicalSize = const Size(412, 1100);
      await tester.pump();
      await tester.pump();
      final view = tester.getRect(viewer);
      expect(shift(tester).dy, lessThanOrEqualTo(0));
      expect(page(tester, 2).bottom + 16, closeTo(view.bottom, 0.5));
    });

    testWidgets('TalkBack can scroll the stack, and that holds follow', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await pumpPlayback(tester, paged(), size: small);
      final scrollable = find.semantics.byAction(SemanticsAction.scrollUp);
      expect(scrollable, findsOne);
      final node = scrollable.evaluate().single;
      bool has(SemanticsAction action) =>
          node.getSemanticsData().hasAction(action);
      // At the top, at 1x: only down the stack.
      expect(has(SemanticsAction.scrollDown), isFalse);
      expect(has(SemanticsAction.scrollLeft), isFalse);

      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      final viewHeight = tester.getRect(viewer).height;
      tester.semantics.scrollUp(scrollable: scrollable);
      await tester.pump();
      expect(shift(tester).dy, closeTo(-0.8 * viewHeight, 0.5));
      final held = shift(tester);
      await tester.pump(const Duration(milliseconds: 1500));
      await settleFollow(tester);
      expect(shift(tester), held);

      tester.semantics.scrollDown(scrollable: scrollable);
      await tester.pump();
      expect(shift(tester).dy, 0);

      await pinchTo(tester, 2);
      final zoomed = scrollable.evaluate().single;
      expect(
        zoomed.getSemanticsData().hasAction(SemanticsAction.scrollLeft),
        isTrue,
      );
      final x = shift(tester).dx;
      tester.semantics.scrollLeft(scrollable: scrollable);
      await tester.pump();
      expect(shift(tester).dx, lessThan(x - 50));
      handle.dispose();
    });

    testWidgets('reopening the score starts at 1x', (tester) async {
      final harness = paged();
      await pumpPlayback(tester, harness, size: small);
      await pinchTo(tester, 2);
      expect(scale(tester), greaterThan(1.5));
      await tester.tap(find.byTooltip(PlaybackMessages.back));
      await settle(tester);
      await tester.pump(const Duration(seconds: 1));
      await reopenPlayback(tester);
      expect(scale(tester), 1);
      expect(shift(tester), Offset.zero);
    });

    testWidgets('at 1x a vertical drag scrolls the stack, sideways does not', (
      tester,
    ) async {
      await pumpPlayback(tester, paged(), size: small);
      await drag(tester, const Offset(0, -200));
      expect(shift(tester).dy, lessThan(-150));
      final y = shift(tester).dy;
      await drag(tester, const Offset(-80, 0));
      expect(shift(tester), Offset(0, y));
    });

    testWidgets('zoomed, one finger pans both ways and reaches page 2', (
      tester,
    ) async {
      await pumpPlayback(tester, paged(), size: small);
      await pinchTo(tester, 2);
      final start = shift(tester);
      await drag(tester, const Offset(-60, -80));
      final moved = shift(tester);
      expect(moved.dx, lessThan(start.dx - 30));
      expect(moved.dy, lessThan(start.dy - 40));
      // V2.4 AC5: the whole stack is still reachable while zoomed.
      for (var i = 0; i < 6; i++) {
        await drag(tester, const Offset(0, -250));
      }
      expect(page(tester, 1).top, lessThan(tester.getRect(viewer).bottom));
      expect(scale(tester), closeTo(2, 0.05));
    });

    testWidgets('pages are joined top to bottom, in order (V2.4 AC1)', (
      tester,
    ) async {
      await pumpPlayback(tester, paged(), size: small);
      expect(page(tester, 1).top, closeTo(page(tester, 0).bottom + 12, 0.01));
      expect(page(tester, 2).top, closeTo(page(tester, 1).bottom + 12, 0.01));
    });

    testWidgets('a one-page score sits where it did before zoom (V2.4 AC6)', (
      tester,
    ) async {
      await pumpPlayback(tester, ready(review: false));
      final view = tester.getRect(viewer);
      final only = page(tester, 0);
      expect(only.left, view.left + 12);
      expect(only.top, view.top + 8);
      expect(only.width, view.width - 24);
    });

    testWidgets('while playing, the band crossing pages scrolls them in', (
      tester,
    ) async {
      await pumpPlayback(tester, paged(), size: small);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));
      expect(inView(tester, band(tester)), isTrue);
      expect(inView(tester, page(tester, 1)), isFalse);

      await tester.pump(const Duration(milliseconds: 1000));
      await settleFollow(tester);
      expect(band(tester).top, greaterThan(page(tester, 1).top));
      expect(inView(tester, band(tester)), isTrue);
      // The follow scroll itself is not a manual scroll: page 3 follows.
      await tester.pump(const Duration(milliseconds: 1000));
      await settleFollow(tester);
      expect(band(tester).top, greaterThan(page(tester, 2).top));
      expect(inView(tester, band(tester)), isTrue);
    });

    testWidgets('a manual scroll stops auto-follow until play is tapped', (
      tester,
    ) async {
      await pumpPlayback(tester, paged(), size: small);
      final play = find.byKey(const ValueKey('play-pause'));
      await tester.tap(play);
      await tester.pump();
      await drag(tester, const Offset(0, -60));
      final held = shift(tester);
      // Well past the 3 s the old grace allowed, across two page turns.
      await tester.pump(const Duration(milliseconds: 2400));
      await settleFollow(tester);
      expect(band(tester).top, greaterThan(page(tester, 2).top));
      expect(shift(tester), held);
      expect(inView(tester, band(tester)), isFalse);

      await tester.tap(play); // pause: still hands off
      await settleFollow(tester);
      expect(shift(tester), held);
      await tester.tap(play);
      await tester.pump();
      await settleFollow(tester);
      expect(inView(tester, band(tester)), isTrue);
    });

    testWidgets('a pinch stops auto-follow too; a seek brings it back', (
      tester,
    ) async {
      await pumpPlayback(tester, paged(), size: small);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await pinchTo(tester, 2);
      final held = shift(tester);
      await tester.pump(const Duration(milliseconds: 1500));
      await settleFollow(tester);
      expect(shift(tester), held);
      expect(inView(tester, band(tester)), isFalse);

      // Paused first, so the band holds still for the check: at 2x it
      // sweeps a page width in half a second while playing.
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await tapTooltip(tester, PlaybackMessages.toLastBar);
      await settleFollow(tester);
      expect(band(tester).top, greaterThan(page(tester, 2).top));
      expect(inView(tester, band(tester)), isTrue);
      expect(scale(tester), closeTo(2, 0.05));
    });

    testWidgets('a seek scrolls to the target page, also while zoomed', (
      tester,
    ) async {
      await pumpPlayback(tester, paged(), size: small);
      await tapTooltip(tester, PlaybackMessages.toLastBar);
      await settleFollow(tester);
      expect(band(tester).top, greaterThan(page(tester, 2).top));
      expect(inView(tester, band(tester)), isTrue);

      await tapTooltip(tester, PlaybackMessages.toStart);
      await settleFollow(tester);
      await pinchTo(tester, 3);
      await tapTooltip(tester, PlaybackMessages.toLastBar);
      await settleFollow(tester);
      expect(inView(tester, band(tester)), isTrue);
      expect(scale(tester), closeTo(3, 0.1));
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

  group('voice chips (PIYA-208-V2.5)', () {
    const fills = {
      VoicePart.soprano: AppTheme.mixerSoprano,
      VoicePart.alto: AppTheme.mixerAlto,
      VoicePart.tenor: AppTheme.mixerTenor,
      VoicePart.bass: AppTheme.mixerBass,
    };
    // The test font is Ahem (1 em per glyph); load the SDK's Roboto so chip
    // widths are realistic. Without FLUTTER_ROOT the width test is skipped.
    final flutterRoot = Platform.environment['FLUTTER_ROOT'];
    final fontsSkip = flutterRoot == null
        ? 'FLUTTER_ROOT is unset, so the SDK Roboto cannot be loaded'
        : null;
    setUpAll(() async {
      if (flutterRoot == null) return;
      final root = flutterRoot;
      final loader = FontLoader('Roboto');
      for (final f in ['regular', 'bold', 'medium']) {
        final bytes = File(
          '$root/bin/cache/artifacts/material_fonts/roboto-$f.ttf',
        ).readAsBytesSync();
        loader.addFont(Future.value(ByteData.sublistView(bytes)));
      }
      await loader.load();
    });

    double ratio(Color a, Color b) {
      final hi = a.computeLuminance(), lo = b.computeLuminance();
      return (math.max(hi, lo) + 0.05) / (math.min(hi, lo) + 0.05);
    }

    // One line is guaranteed only at text scale 1.0; above that the Wrap
    // lets chips wrap for NFR-10 rather than clip.
    testWidgets('AC1: all four on one line at 360 dp, scale 1.0, with 12% '
        'slack for the wider Plus Jakarta Sans', (tester) async {
      await pumpPlayback(tester, ready(), size: const Size(360, 800));
      final tops = [
        for (final v in VoicePart.values) tester.getTopLeft(chip(v)).dy,
      ];
      expect(tops.toSet(), hasLength(1), reason: '$tops');
      // Roboto stands in for Plus Jakarta Sans (about 8-10% wider, not
      // available offline): the row must end 12% short of the 328 dp width
      // between the 16 dp gutters.
      expect(
        tester.getRect(chip(VoicePart.bass)).right,
        lessThanOrEqualTo(16 + 0.88 * 328),
      );
      for (final v in VoicePart.values) {
        expect(tester.getSize(chip(v)).height, greaterThanOrEqualTo(48));
      }
      expect(tester.takeException(), isNull);
    }, skip: fontsSkip != null);

    testWidgets('AC1: large text wraps instead of overflowing', (tester) async {
      await pumpPlayback(
        tester,
        ready(),
        size: const Size(360, 800),
        textScale: 2,
      );
      expect(tester.takeException(), isNull);
      for (final v in VoicePart.values) {
        expect(tester.getRect(chip(v)).right, lessThanOrEqualTo(360));
      }
    });

    testWidgets('AC2/AC3: selected fill is the mixer colour, label and tick '
        'pass 4.5:1', (tester) async {
      await pumpPlayback(tester, ready(), size: const Size(360, 800));
      for (final MapEntry(:key, :value) in fills.entries) {
        final c = tester.widget<FilterChip>(chip(key));
        expect(c.selectedColor, value, reason: key.name);
        // The painted fill, not just the property: FilterChip paints it as an
        // Ink ShapeDecoration (its Material has no colour of its own).
        final ink = tester.widget<Ink>(
          find.descendant(of: chip(key), matching: find.byType(Ink)),
        );
        expect(
          (ink.decoration! as ShapeDecoration).color,
          value,
          reason: key.name,
        );
        expect(c.labelStyle!.color, Colors.white, reason: key.name);
        expect(c.checkmarkColor, Colors.white, reason: key.name);
        final r = ratio(c.labelStyle!.color!, value);
        expect(r, greaterThanOrEqualTo(4.5), reason: key.name);
      }
    });

    testWidgets('AC4: unselected and disabled chips keep their look', (
      tester,
    ) async {
      await pumpPlayback(
        tester,
        ready(voices: {VoicePart.soprano, VoicePart.alto}, review: false),
        size: const Size(360, 800),
      );
      // Missing voices open the failed-voices alert, whose barrier covers the
      // chips by design; answer it, then tap the chip for real.
      await tester.tap(find.text(PlaybackMessages.ok));
      await tester.pumpAndSettle();
      await tester.tap(chip(VoicePart.alto));
      await tester.pump();
      final off = tester.widget<FilterChip>(chip(VoicePart.alto));
      expect(off.selected, isFalse);
      expect(off.backgroundColor, AppTheme.playbackChipFill);
      expect(off.labelStyle!.color, AppTheme.playbackChipText);
      final gone = tester.widget<FilterChip>(chip(VoicePart.bass));
      expect(
        gone.disabledColor,
        AppTheme.playbackChipFill.withValues(alpha: 0.45),
      );
      expect(
        gone.labelStyle!.color,
        AppTheme.playbackChipText.withValues(alpha: 0.45),
      );
      expect(gone.labelStyle!.decoration, TextDecoration.lineThrough);
    });
  });
}
