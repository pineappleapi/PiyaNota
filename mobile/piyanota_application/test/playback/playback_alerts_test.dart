import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_platform_interface.dart';
import 'package:shared_preferences_platform_interface/types.dart';

import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/playback_alerts.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/screens/playback/sheet_parts.dart';
import 'package:piyanota_application/state/playback_providers.dart';

import 'playback_fakes.dart';

/// A preferences store whose reads or writes throw (a corrupt or
/// unavailable store on a real device).
class _FaultyPrefsStore extends InMemorySharedPreferencesStore {
  _FaultyPrefsStore(super.data, {this.readFails = false}) : super.withData();

  final bool readFails;
  int writes = 0;

  @override
  Future<Map<String, Object>> getAll() =>
      readFails ? Future.error(StateError('prefs unreadable')) : super.getAll();

  @override
  Future<Map<String, Object>> getAllWithPrefix(String prefix) => readFails
      ? Future.error(StateError('prefs unreadable'))
      : super.getAllWithPrefix(prefix);

  @override
  Future<Map<String, Object>> getAllWithParameters(
    GetAllParameters parameters,
  ) => readFails
      ? Future.error(StateError('prefs unreadable'))
      : super.getAllWithParameters(parameters);

  @override
  Future<bool> setValue(String valueType, String key, Object value) {
    writes++;
    return Future.error(StateError('prefs unwritable'));
  }
}

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

  // What debugPrint printed during a [testWidgetsPrinting] test. Restored
  // inside the test body: the binding checks debugPrint before tear-down.
  late List<String> printed;
  void testWidgetsPrinting(String description, WidgetTesterCallback body) =>
      testWidgets(description, (tester) async {
        printed = [];
        final saved = debugPrint;
        debugPrint = (message, {wrapWidth}) => printed.add(message ?? '');
        try {
          await body(tester);
        } finally {
          debugPrint = saved;
        }
      });

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

      // A later dropout re-raises the failed alert (for the new voice),
      // but the muted alert is not shown a second time.
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      h.engine.fail(VoicePart.alto);
      await tester.pump();
      await tester.pump();
      expect(
        find.text(PlaybackMessages.failedVoicesTitle([VoicePart.alto])),
        findsOneWidget,
      );
      expect(mutedAlert, findsNothing);
      await ok(tester);
      expect(mutedAlert, findsNothing);
      expect(failedAlert, findsNothing);
    });

    testWidgets('the onboarding voice failed on the server: every other '
        'voice is selected, and the alert names it', (tester) async {
      final h = harness(
        voices: {VoicePart.soprano, VoicePart.alto, VoicePart.bass},
        failed: {VoicePart.tenor},
      );
      await pumpPlayback(tester, h, defaultVoice: VoicePart.tenor);
      expect(failedAlert, findsOneWidget);
      expect(
        find.text(PlaybackMessages.failedVoicesBody([VoicePart.tenor], 3)),
        findsOneWidget,
      );
      expect(controller(tester).state.selected, {
        VoicePart.soprano,
        VoicePart.alto,
        VoicePart.bass,
      });
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

    testWidgetsPrinting('preferences unreadable: the alert is shown', (
      tester,
    ) async {
      await pumpPlayback(
        tester,
        harness(mutedMeasures: [muted]),
        prefs: {MutedAlertPrefs.keyFor(kScoreId): true},
        prefsStore: (values) => _FaultyPrefsStore(values, readFails: true),
      );
      await settle(tester);
      expect(mutedAlert, findsOneWidget);
      expect(
        printed,
        contains(startsWith('Playback: muted-alert preference unread')),
      );
    });

    testWidgetsPrinting(
      'preferences unwritable: Don\'t show again is logged, the '
      'alert still closes',
      (tester) async {
        late _FaultyPrefsStore store;
        await pumpPlayback(
          tester,
          harness(mutedMeasures: [muted]),
          prefsStore: (values) => store = _FaultyPrefsStore(values),
        );
        expect(mutedAlert, findsOneWidget);
        await tester.tap(find.byKey(const ValueKey('muted-dont-show-again')));
        await tester.pump();
        await ok(tester);
        expect(mutedAlert, findsNothing);
        expect(store.writes, 1);
        expect(
          printed,
          contains(startsWith('Playback: muted-alert preference not saved')),
        );
        expect(tester.takeException(), isNull);
      },
    );

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

    group('click files', () {
      late Directory dir;
      late List<File> written;
      // Writer calls (by index) that throw instead of writing.
      late Set<int> writeFailsAt;

      setUp(() {
        dir = Directory.systemTemp.createTempSync('piyanota_click_test');
        written = [];
        writeFailsAt = {};
        addTearDown(() => dir.deleteSync(recursive: true));
      });

      PlaybackHarness fileHarness() => PlaybackHarness(
        ScriptedScoreResultApi(
          [testResult()],
          timing: testTiming(),
          bars: sixEight,
        ),
        clickWriter: (plan) async {
          final index = written.length;
          if (writeFailsAt.remove(index)) {
            written.add(File('${dir.path}/unwritten$index.wav'));
            throw const FileSystemException('disk full');
          }
          final file = File('${dir.path}/click$index.wav')
            ..writeAsBytesSync([0]);
          written.add(file);
          return file.uri;
        },
      );

      // Deletion is real file I/O, outside the fake clock.
      Future<void> flushIo(WidgetTester tester) async {
        await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 50)),
        );
        await tester.pump();
      }

      bool exists(int index) => written[index].existsSync();

      void noDoubleDelete() => expect(
        printed.where((p) => p.contains('click file not deleted')),
        isEmpty,
      );

      Future<void> replan(WidgetTester tester, int bpm) async {
        controller(tester)
          ..setBpm(bpm)
          ..commitBpm();
        await tester.pump();
      }

      testWidgetsPrinting(
        'a re-plan swaps the files: only the new one is kept',
        (tester) async {
          final h = fileHarness();
          await pumpPlayback(tester, h);
          await replan(tester, 80);
          await settle(tester);
          await flushIo(tester);
          expect(h.engine.click, written[1].uri);
          expect([exists(0), exists(1)], [false, true]);
          noDoubleDelete();
        },
      );

      testWidgetsPrinting(
        'two overlapping re-plans: only the latest stays, the '
        'other file is deleted',
        (tester) async {
          final h = fileHarness();
          await pumpPlayback(tester, h);
          // Attach call 1 (the first re-plan's) hangs until released.
          final gate = Completer<bool>();
          h.engine.attachGateAt[1] = gate;
          await replan(tester, 80);
          await settle(tester);
          expect(h.engine.attachCalls, hasLength(2));
          // Released before the first attaches: back above 60.
          await replan(tester, 100);
          await settle(tester);
          expect(h.engine.attachCalls, hasLength(3));
          gate.complete(true);
          await settle(tester);
          await flushIo(tester);

          expect(h.clickPlans, hasLength(3));
          expect(h.engine.click, written[2].uri);
          expect(h.engine.attachedClicks.last, written[2].uri);
          expect([exists(0), exists(1), exists(2)], [false, false, true]);
          expect(controller(tester).state.clickStatus, ClickStatus.ready);
          noDoubleDelete();
        },
      );

      testWidgetsPrinting(
        'leaving the screen mid-swap: both files deleted, once '
        'each',
        (tester) async {
          final h = fileHarness();
          await pumpPlayback(tester, h);
          final gate = Completer<bool>();
          h.engine.attachGateAt[1] = gate;
          await replan(tester, 80);
          await settle(tester);

          await tester.tap(find.byTooltip(PlaybackMessages.back));
          await settle(tester);
          await tester.pump(const Duration(seconds: 1));
          expect(h.engine.disposed, isTrue);
          gate.complete(true);
          await tester.pump();
          await flushIo(tester);

          expect([exists(0), exists(1)], [false, false]);
          expect(h.engine.attachedClicks, [written[0].uri]);
          noDoubleDelete();
        },
      );

      testWidgetsPrinting(
        'the re-planned click fails to attach: the old click is '
        'kept, and the next release tries again',
        (tester) async {
          final h = fileHarness();
          await pumpPlayback(tester, h);
          h.engine.attachOutcomeAt[1] = false;
          await replan(tester, 80);
          await settle(tester);
          await flushIo(tester);

          expect(h.engine.attachCalls, [
            written[0].uri,
            written[1].uri,
            written[0].uri,
          ]);
          expect(h.engine.click, written[0].uri);
          expect([exists(0), exists(1)], [true, false]);
          expect(controller(tester).state.clickStatus, ClickStatus.ready);
          expect(
            printed,
            contains(
              contains('re-planned click not attached; keeping the old'),
            ),
          );

          // The old plan is still the planned one, so a release re-plans.
          await replan(tester, 79);
          await settle(tester);
          await flushIo(tester);
          expect(h.clickPlans, hasLength(3));
          expect(h.engine.click, written[2].uri);
          expect([exists(0), exists(2)], [false, true]);
          noDoubleDelete();
        },
      );

      testWidgetsPrinting(
        'neither the new nor the old click attaches: the click '
        'is unavailable and both files are deleted',
        (tester) async {
          final h = fileHarness();
          await pumpPlayback(tester, h);
          h.engine
            ..attachOutcomeAt[1] = false
            ..attachOutcomeAt[2] = false;
          await replan(tester, 80);
          await settle(tester);
          await flushIo(tester);
          expect(controller(tester).state.clickStatus, ClickStatus.unavailable);
          expect(h.engine.click, isNull);
          expect([exists(0), exists(1)], [false, false]);
          noDoubleDelete();
        },
      );

      testWidgetsPrinting(
        'the re-planned click fails to write: the old click is '
        'kept',
        (tester) async {
          final h = fileHarness();
          await pumpPlayback(tester, h);
          writeFailsAt.add(1);
          await replan(tester, 80);
          await settle(tester);
          await flushIo(tester);
          expect(h.engine.detachCalls, 0);
          expect(h.engine.click, written[0].uri);
          expect(exists(0), isTrue);
          expect(controller(tester).state.clickStatus, ClickStatus.ready);
          expect(printed, contains(contains('metronome click not generated')));
        },
      );
    });
  });
}
