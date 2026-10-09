import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/screens/playback/sheet_parts.dart';
import 'package:piyanota_application/state/playback_providers.dart';

import 'playback_fakes.dart';

/// PIYA-210 Playback Speed. The fake engine's `speed` is what the real one
/// passes to just_audio's pitch-preserving `setSpeed`; pitch itself can
/// only be checked on a device.
void main() {
  PlaybackHarness ready({int tempoBpm = 90, bool clickAttachFails = false}) =>
      PlaybackHarness(
        ScriptedScoreResultApi([
          testResult(tempoBpm: tempoBpm),
        ], timing: testTiming()),
        clickAttachFails: clickAttachFails,
      );

  final slider = find.byKey(const ValueKey('speed-slider'));
  final toggle = find.byKey(const ValueKey('metronome-toggle'));
  String bpmText(WidgetTester tester) =>
      tester.widget<Text>(find.byKey(const ValueKey('speed-bpm'))).data!;
  double sliderValue(WidgetTester tester) =>
      tester.widget<Slider>(slider).value;
  String positionText(WidgetTester tester) =>
      tester.widget<Text>(find.byKey(const ValueKey('time-position'))).data!;
  PlaybackController controller(WidgetTester tester) =>
      appContainer(tester).read(playbackControllerProvider(kScoreId).notifier);

  Future<void> openSpeed(WidgetTester tester) async {
    await tester.tap(find.bySemanticsLabel(PlaybackMessages.speed));
    await settle(tester);
    expect(find.byKey(const ValueKey('speed-sheet')), findsOneWidget);
  }

  Future<void> close(WidgetTester tester) async {
    await tester.tap(find.byTooltip(PlaybackMessages.close));
    await settle(tester);
  }

  /// Taps the slider where [bpm] sits on its 30-240 track.
  Future<void> tapBpm(WidgetTester tester, int bpm) async {
    final rect = tester.getRect(slider);
    const inset = 18.0;
    final fraction = (bpm - 30) / 210;
    await tester.tapAt(
      Offset(
        rect.left + inset + (rect.width - 2 * inset) * fraction,
        rect.center.dy,
      ),
    );
    await tester.pump();
  }

  group('slider (AC1, AC2, AC4)', () {
    testWidgets('opens at 90 BPM, the default tempo, at 1x', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await openSpeed(tester);

      expect(find.text(PlaybackMessages.speedTitle), findsWidgets);
      expect(find.text(PlaybackMessages.speedSubtitle), findsOneWidget);
      expect(find.text(PlaybackMessages.playbackSpeed), findsOneWidget);
      expect(sliderValue(tester), 90);
      expect(bpmText(tester), '90');
      final widget = tester.widget<Slider>(slider);
      expect(widget.min, 30);
      expect(widget.max, 240);
      expect(widget.divisions, 210);
      expect(harness.engine.speed, 1);
    });

    testWidgets('a score rendered at another tempo opens at that tempo', (
      tester,
    ) async {
      final harness = ready(tempoBpm: 120);
      await pumpPlayback(tester, harness);
      await openSpeed(tester);
      expect(sliderValue(tester), 120);
      expect(harness.engine.speed, 1);

      controller(tester).setBpm(60);
      await tester.pump();
      expect(harness.engine.speed, 0.5);
    });

    testWidgets('dragging while playing changes speed at once, no restart', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await openSpeed(tester);
      final playsBefore = harness.engine.playCalls;
      final seeksBefore = harness.engine.seeks.length;

      await tapBpm(tester, 180);
      final bpm = sliderValue(tester).round();
      expect(bpm, closeTo(180, 3));
      expect(bpmText(tester), '$bpm');
      expect(harness.engine.speed, bpm / 90);

      await tester.drag(slider, const Offset(-60, 0));
      await tester.pump();
      final dragged = sliderValue(tester).round();
      expect(dragged, lessThan(bpm));
      expect(harness.engine.speed, dragged / 90);

      expect(harness.engine.playing, isTrue);
      expect(harness.engine.pauseCalls, 0);
      expect(harness.engine.playCalls, playsBefore);
      expect(harness.engine.seeks, hasLength(seeksBefore));
    });

    testWidgets('the slider is whole BPM, clamped to 30-240', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      final c = controller(tester);
      c.setBpm(10);
      expect(c.state.chosenBpm, 30);
      expect(harness.engine.speed, 30 / 90);
      c.setBpm(999);
      expect(c.state.chosenBpm, 240);
      expect(harness.engine.speed, 240 / 90);
    });
  });

  group('metronome click (AC3)', () {
    testWidgets('off by default; the toggle turns the click on and off', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await openSpeed(tester);
      expect(tester.widget<SheetCheckbox>(toggle).value, isFalse);
      expect(harness.engine.clickVolume, 0);

      await tester.tap(toggle);
      await tester.pump();
      expect(tester.widget<SheetCheckbox>(toggle).value, isTrue);
      expect(harness.engine.clickVolume, 1);

      await tester.tap(toggle);
      await tester.pump();
      expect(harness.engine.clickVolume, 0);
    });

    testWidgets('independent of the mixer metronome row', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      final c = controller(tester)..setClickMuted(muted: true);
      await openSpeed(tester);

      await tester.tap(toggle);
      await tester.pump();
      // On here, but the mixer's Mute still holds it silent...
      expect(c.state.metronomeOn, isTrue);
      expect(harness.engine.clickVolume, 0);
      // ...and unmuting there doesn't need the toggle again.
      c.setClickMuted(muted: false);
      expect(harness.engine.clickVolume, 1);
      // Turning it off here leaves the mixer's level alone.
      c.setClickVolume(0.4);
      await tester.tap(toggle);
      await tester.pump();
      expect(harness.engine.clickVolume, 0);
      expect(c.state.clickVolume, 0.4);
      expect(c.state.clickMuted, isFalse);
    });

    testWidgets('synced to the tempo: the click is planned at tempoBpm and '
        'stretched by the same speed as the voices', (tester) async {
      final harness = ready(tempoBpm: 120);
      await pumpPlayback(tester, harness);
      final plan = harness.clickPlans.single;
      // testTiming() bar 1 starts at t = 0; 120 BPM is a click every 0.5 s.
      expect(plan.clicks.take(3), const [
        Duration.zero,
        Duration(milliseconds: 500),
        Duration(seconds: 1),
      ]);
      expect(plan.length, harness.engine.duration);
      controller(tester).setBpm(150);
      // One engine speed for voices and click: the click is heard at 150.
      expect(harness.engine.speed, 1.25);
    });

    testWidgets('a click that will not load: toggle disabled, with a note', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      final harness = ready(clickAttachFails: true);
      await pumpPlayback(tester, harness);
      await openSpeed(tester);
      expect(tester.widget<SheetCheckbox>(toggle).onChanged, isNull);
      expect(find.text(PlaybackMessages.metronomeUnavailable), findsOneWidget);
      // Speed still works.
      controller(tester).setBpm(45);
      expect(harness.engine.speed, 0.5);
      expect(tester.widget<Slider>(slider).onChanged, isNotNull);
      handle.dispose();
    });
  });

  group('session (AC5)', () {
    testWidgets('X closes onto Playback without interrupting it', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await openSpeed(tester);
      await tapBpm(tester, 135);
      final speed = harness.engine.speed;
      final before = positionText(tester);
      await tester.pump(const Duration(milliseconds: 1500));
      expect(positionText(tester), isNot(before));

      await close(tester);
      expect(find.byKey(const ValueKey('speed-sheet')), findsNothing);
      expect(harness.engine.playing, isTrue);
      expect(harness.engine.pauseCalls, 0);
      expect(harness.engine.speed, speed);
      expect(find.text(kTitle), findsOneWidget);
    });

    testWidgets('settings last for the session, reset on reopen', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await openSpeed(tester);
      await tapBpm(tester, 150);
      await tester.tap(toggle);
      await tester.pump();
      final bpm = sliderValue(tester);
      await close(tester);
      await openSpeed(tester);
      expect(sliderValue(tester), bpm);
      expect(tester.widget<SheetCheckbox>(toggle).value, isTrue);
      await close(tester);

      await tester.tap(find.byTooltip(PlaybackMessages.back));
      await settle(tester);
      await tester.pump(const Duration(seconds: 1));
      await reopenPlayback(tester);
      expect(harness.engine.speed, 1);
      expect(harness.engine.clickVolume, 0);
      await openSpeed(tester);
      expect(sliderValue(tester), 90);
      expect(tester.widget<SheetCheckbox>(toggle).value, isFalse);
    });
  });

  group('layout and accessibility', () {
    for (final (name, size, scale) in [
      ('320 dp', const Size(320, 568), 1.0),
      ('360 dp at 1.3x text', const Size(360, 740), 1.3),
      ('412 dp at 2x text', const Size(412, 917), 2.0),
    ]) {
      testWidgets('fits without overflow: $name', (tester) async {
        await pumpPlayback(tester, ready(), size: size, textScale: scale);
        await openSpeed(tester);
        expect(tester.takeException(), isNull);
        final box = tester.getRect(toggle);
        expect(box.width, greaterThanOrEqualTo(48));
        expect(box.height, greaterThanOrEqualTo(48));
      });
    }

    testWidgets('labels and guidelines', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpPlayback(tester, ready());
      await openSpeed(tester);
      expect(
        tester.getSemantics(slider),
        matchesSemantics(
          label: PlaybackMessages.playbackSpeed,
          value: PlaybackMessages.bpmSpoken(90),
          increasedValue: PlaybackMessages.bpmSpoken(91),
          decreasedValue: PlaybackMessages.bpmSpoken(89),
          isEnabled: true,
          hasEnabledState: true,
          isFocusable: true,
          hasIncreaseAction: true,
          hasDecreaseAction: true,
          hasFocusAction: true,
          isSlider: true,
        ),
      );
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      handle.dispose();
    });
  });
}
