import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/playback_alerts.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/screens/playback/sheet_parts.dart';
import 'package:piyanota_application/state/playback_providers.dart';

import 'playback_fakes.dart';

/// Gap items 4-7 (docs/decisions/meter-click-and-muting-gaps.md): the
/// failed-voice and muted-measure alerts on Playback, the solo-on-an-off-
/// chip alert in the Voice Mixer, and the click re-plan on slider release.
void main() {
  const muted = MutedMeasure(
    voice: VoicePart.bass,
    bar: 4,
    pageIndex: 0,
    systemIndex: 0,
    startMs: 1500,
    endMs: 2000,
  );

  final failedAlert = find.byKey(const ValueKey('failed-voices-alert'));
  final mutedAlert = find.byKey(const ValueKey('muted-measures-alert'));
  final soloAlert = find.byKey(const ValueKey('solo-chip-off-alert'));

  PlaybackController controller(WidgetTester tester) =>
      appContainer(tester).read(playbackControllerProvider(kScoreId).notifier);

  PlaybackHarness harness({
    Set<VoicePart> voices = const {...VoicePart.values},
    Set<VoicePart> failed = const {},
    List<MutedMeasure> mutedMeasures = const [],
    Set<VoicePart> failAtLoad = const {},
    List<BarInfo>? bars,
  }) => PlaybackHarness(
    ScriptedScoreResultApi(
      [
        testResult(
          voices: voices,
          failedVoices: failed,
          mutedMeasures: mutedMeasures,
        ),
      ],
      timing: testTiming(),
      bars: bars,
    ),
    engineFailAtLoad: failAtLoad,
  );

  Future<void> ok(WidgetTester tester) async {
    await tester.tap(find.text(PlaybackMessages.ok));
    await settle(tester);
  }

  group('failed voices (items 4, 6, 7; PIYA-216 AC5)', () {
    testWidgets('a voice failed on the server: alert naming it, the other '
        'three play', (tester) async {
      final h = harness(
        voices: {VoicePart.soprano, VoicePart.alto, VoicePart.bass},
        failed: {VoicePart.tenor},
      );
      await pumpPlayback(tester, h);
      expect(failedAlert, findsOneWidget);
      expect(
        find.text(PlaybackMessages.failedVoicesBody([VoicePart.tenor], 3)),
        findsOneWidget,
      );
      await ok(tester);
      expect(failedAlert, findsNothing);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      expect(h.engine.playing, isTrue);
    });

    testWidgets('failed first, then muted; neither twice', (tester) async {
      final h = harness(
        voices: {VoicePart.soprano, VoicePart.alto, VoicePart.bass},
        failed: {VoicePart.tenor},
        mutedMeasures: [muted],
      );
      await pumpPlayback(tester, h);
      expect(failedAlert, findsOneWidget);
      expect(mutedAlert, findsNothing);
      await ok(tester);
      expect(mutedAlert, findsOneWidget);
      expect(find.text(PlaybackMessages.mutedLine(muted)), findsOneWidget);
      // Don't show again is on the muted alert only (item 6).
      expect(find.byKey(const ValueKey('muted-dont-show-again')), findsOne);
      await ok(tester);
      expect(mutedAlert, findsNothing);
      expect(failedAlert, findsNothing);

      // A later state change on the same screen doesn't repeat either.
      controller(tester).setBpm(100);
      await settle(tester);
      expect(mutedAlert, findsNothing);
      expect(failedAlert, findsNothing);
    });

    testWidgets('a mid-play dropout: the same alert, and its Mixer row is '
        'disabled (item 7)', (tester) async {
      final h = harness();
      await pumpPlayback(tester, h);
      expect(failedAlert, findsNothing);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      h.engine.fail(VoicePart.alto);
      await tester.pump();
      await tester.pump();
      expect(
        find.text(PlaybackMessages.failedVoicesTitle([VoicePart.alto])),
        findsOneWidget,
      );
      expect(
        find.text(PlaybackMessages.failedVoicesBody([VoicePart.alto], 3)),
        findsOneWidget,
      );
      await ok(tester);
      expect(h.engine.playing, isTrue);

      await tester.tap(find.bySemanticsLabel(PlaybackMessages.voiceMixer));
      await settle(tester);
      final alto = find.byKey(const ValueKey('mixer-row-alto'));
      expect(alto, findsOneWidget);
      expect(
        tester
            .widget<Slider>(
              find.descendant(of: alto, matching: find.byType(Slider)),
            )
            .onChanged,
        isNull,
      );
    });
  });

  group('muted measures (items 5, 6)', () {
    testWidgets('Don\'t show again is saved for this score only', (
      tester,
    ) async {
      await pumpPlayback(tester, harness(mutedMeasures: [muted]));
      expect(mutedAlert, findsOneWidget);
      expect(find.text(PlaybackMessages.mutedTitle), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('muted-dont-show-again')));
      await tester.pump();
      await ok(tester);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getBool(MutedAlertPrefs.keyFor(kScoreId)), isTrue);
      expect(prefs.getBool(MutedAlertPrefs.keyFor(kScoreId + 1)), isNull);
    });

    testWidgets('left unticked, nothing is saved', (tester) async {
      await pumpPlayback(tester, harness(mutedMeasures: [muted]));
      await ok(tester);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getBool(MutedAlertPrefs.keyFor(kScoreId)), isNull);
    });

    testWidgets('once hidden, the alert stays away for that score', (
      tester,
    ) async {
      await pumpPlayback(
        tester,
        harness(mutedMeasures: [muted]),
        prefs: {MutedAlertPrefs.keyFor(kScoreId): true},
      );
      await settle(tester);
      expect(mutedAlert, findsNothing);
    });

    testWidgets('no muted measures, no alert', (tester) async {
      await pumpPlayback(tester, harness());
      await settle(tester);
      expect(mutedAlert, findsNothing);
      expect(failedAlert, findsNothing);
    });

    test('lines read as a choir member would say them', () {
      expect(PlaybackMessages.mutedLine(muted), 'Bass: m. 4');
      expect(
        PlaybackMessages.mutedLine(
          const MutedMeasure(voice: VoicePart.alto, pageIndex: 0),
        ),
        'Alto: page 1',
      );
      expect(
        PlaybackMessages.mutedLine(
          const MutedMeasure(
            voice: VoicePart.alto,
            pageIndex: 1,
            systemIndex: 2,
          ),
        ),
        'Alto: page 2, system 3',
      );
    });
  });

  group('solo on a voice whose chip is off (PIYA-209)', () {
    Future<void> soloAlto(WidgetTester tester) async {
      await tester.tap(find.bySemanticsLabel(PlaybackMessages.voiceMixer));
      await settle(tester);
      await tester.tap(
        find.descendant(
          of: find.byKey(const ValueKey('mixer-row-alto')),
          matching: find.byType(SheetCheckbox),
        ),
      );
      await settle(tester);
    }

    testWidgets('Cancel leaves the chip off and the voice unsoloed', (
      tester,
    ) async {
      await pumpPlayback(tester, harness(), defaultVoice: VoicePart.soprano);
      expect(controller(tester).state.selected, {VoicePart.soprano});
      await soloAlto(tester);
      expect(soloAlert, findsOneWidget);
      expect(
        find.text(PlaybackMessages.soloChipOffTitle(VoicePart.alto)),
        findsOneWidget,
      );
      await tester.tap(find.text(PlaybackMessages.cancel));
      await settle(tester);
      expect(soloAlert, findsNothing);
      expect(controller(tester).state.soloed, isEmpty);
      expect(controller(tester).state.selected, {VoicePart.soprano});
    });

    testWidgets('Turn on: the chip comes on and the voice is soloed', (
      tester,
    ) async {
      await pumpPlayback(tester, harness(), defaultVoice: VoicePart.soprano);
      await soloAlto(tester);
      await tester.tap(find.text(PlaybackMessages.turnOn(VoicePart.alto)));
      await settle(tester);
      final state = controller(tester).state;
      expect(state.selected, containsAll([VoicePart.soprano, VoicePart.alto]));
      expect(state.soloed, {VoicePart.alto});
    });

    testWidgets('a voice whose chip is on solos without asking', (
      tester,
    ) async {
      await pumpPlayback(tester, harness());
      await soloAlto(tester);
      expect(soloAlert, findsNothing);
      expect(controller(tester).state.soloed, {VoicePart.alto});
    });
  });

  group('click re-plan on slider release (PIYA-210 "Speed changes")', () {
    // testTiming() is 4 s at 90 BPM; one 6/8 bar long enough to cover it.
    const sixEight = [
      BarInfo(
        bar: 1,
        startTick: 0,
        durTicks: 1440 * 5,
        numerator: 6,
        denominator: 8,
        meterSource: MeterSource.detected,
      ),
    ];

    testWidgets('no change in subdivision: no re-plan', (tester) async {
      final h = harness(bars: sixEight);
      await pumpPlayback(tester, h);
      expect(h.clickPlans, hasLength(1));
      controller(tester)
        ..setBpm(120)
        ..commitBpm();
      await settle(tester);
      expect(h.clickPlans, hasLength(1));
      expect(h.engine.detachCalls, 0);
    });

    testWidgets('6/8 dropping below 60 dotted-quarters a minute re-plans '
        'once, with eighths; and back again', (tester) async {
      final h = harness(bars: sixEight);
      await pumpPlayback(tester, h);
      final first = h.clickPlans.single;
      expect(first.clicks.length, 2 * 5);

      // Mid-drag: nothing re-planned until the slider is let go.
      controller(tester).setBpm(80);
      await settle(tester);
      expect(h.clickPlans, hasLength(1));

      controller(tester).commitBpm();
      await settle(tester);
      expect(h.clickPlans, hasLength(2));
      expect(h.clickPlans.last.clicks.length, 6 * 5);
      expect(h.engine.detachCalls, 1);
      expect(h.engine.attachedClicks, hasLength(2));
      expect(controller(tester).state.clickStatus, ClickStatus.ready);

      controller(tester)
        ..setBpm(100)
        ..commitBpm();
      await settle(tester);
      expect(h.clickPlans, hasLength(3));
      expect(h.clickPlans.last.clicks.length, 2 * 5);
    });
  });
}
