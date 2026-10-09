import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/screens/playback/sheet_parts.dart';
import 'package:piyanota_application/state/playback_providers.dart';

import 'playback_fakes.dart';

/// PIYA-209 Voice Mixer. The engine fake records what actually reaches the
/// audio (per-voice volume, click volume), so these check sound, not just
/// the toggles' look (FR-4/FR-5).
void main() {
  PlaybackHarness ready({
    Set<VoicePart> failAtLoad = const {},
    bool clickAttachFails = false,
    Object? clickWriteError,
  }) => PlaybackHarness(
    ScriptedScoreResultApi([testResult()], timing: testTiming()),
    engineFailAtLoad: failAtLoad,
    clickAttachFails: clickAttachFails,
    clickWriteError: clickWriteError,
  );

  Finder row(String name) => find.byKey(ValueKey('mixer-row-$name'));
  Finder voiceRow(VoicePart voice) => row(voice.name);
  final metronomeRow = row('metronome');
  Finder sliderIn(Finder row) =>
      find.descendant(of: row, matching: find.byType(Slider));
  Finder soloIn(Finder row) =>
      find.descendant(of: row, matching: find.byType(SheetCheckbox));
  Finder muteIn(Finder row) =>
      find.descendant(of: row, matching: find.text(PlaybackMessages.mute));
  double sliderValue(WidgetTester tester, Finder row) =>
      tester.widget<Slider>(sliderIn(row)).value;
  String positionText(WidgetTester tester) =>
      tester.widget<Text>(find.byKey(const ValueKey('time-position'))).data!;
  PlaybackController controller(WidgetTester tester) =>
      appContainer(tester).read(playbackControllerProvider(kScoreId).notifier);

  Future<void> openMixer(WidgetTester tester) async {
    await tester.tap(find.bySemanticsLabel(PlaybackMessages.voiceMixer));
    await settle(tester);
    expect(find.byKey(const ValueKey('mixer-sheet')), findsOneWidget);
  }

  /// Taps [row]'s slider at [fraction] of its track (0 = left).
  Future<void> setSlider(
    WidgetTester tester,
    Finder row,
    double fraction,
  ) async {
    final rect = tester.getRect(sliderIn(row));
    // The track is inset by the overlay radius on each side.
    const inset = 18.0;
    final x = rect.left + inset + (rect.width - 2 * inset) * fraction;
    await tester.tapAt(Offset(x, rect.center.dy));
    // One frame: AC3's "within 100 ms" is checked after a single pump.
    await tester.pump();
  }

  Future<void> tapIn(WidgetTester tester, Finder finder) async {
    await tester.tap(finder);
    await tester.pump();
  }

  group('rows and defaults (AC1, AC2, AC5)', () {
    testWidgets('a row per voice plus Metronome Click, each with a slider, '
        'a Solo box and a Mute toggle; all unmuted at full volume', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await openMixer(tester);

      expect(find.text(PlaybackMessages.mixerTitle), findsWidgets);
      expect(find.text(PlaybackMessages.mixerSubtitle), findsOneWidget);
      for (final r in [
        for (final voice in VoicePart.values) voiceRow(voice),
        metronomeRow,
      ]) {
        expect(r, findsOneWidget);
        expect(sliderIn(r), findsOneWidget);
        expect(soloIn(r), findsOneWidget);
        expect(muteIn(r), findsOneWidget);
        expect(sliderValue(tester, r), 1);
        expect(tester.widget<SheetCheckbox>(soloIn(r)).value, isFalse);
      }
      for (final voice in VoicePart.values) {
        expect(find.text(voice.label), findsWidgets);
        expect(harness.engine.volumes[voice], 1);
      }
      expect(find.text(PlaybackMessages.metronomeClick), findsOneWidget);
      // Metronome click attached, silent until the Speed toggle (210 AC3).
      expect(harness.engine.click, isNotNull);
      expect(harness.engine.clickVolume, 0);
    });

    testWidgets('screen-reader labels name the row', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpPlayback(tester, ready());
      await openMixer(tester);
      for (final name in [
        ...VoicePart.values.map((v) => v.label),
        PlaybackMessages.metronomeClick,
      ]) {
        expect(
          find.bySemanticsLabel(PlaybackMessages.soloLabel(name)),
          findsOneWidget,
        );
        expect(
          find.bySemanticsLabel(PlaybackMessages.muteLabel(name)),
          findsOneWidget,
        );
        expect(
          find.bySemanticsLabel(PlaybackMessages.volumeLabel(name)),
          findsOneWidget,
        );
      }
      handle.dispose();
    });
  });

  group('volume and mute (AC2, AC3, AC4)', () {
    testWidgets('a slider change reaches the engine on the next frame', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await openMixer(tester);

      await setSlider(tester, voiceRow(VoicePart.alto), 0.25);
      final level = sliderValue(tester, voiceRow(VoicePart.alto));
      expect(level, closeTo(0.25, 0.05));
      expect(harness.engine.volumes[VoicePart.alto], level);
      expect(harness.engine.volumes[VoicePart.soprano], 1);
    });

    testWidgets('mute silences without moving the slider; unmute restores', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await openMixer(tester);
      final tenor = voiceRow(VoicePart.tenor);

      await setSlider(tester, tenor, 0.5);
      final level = sliderValue(tester, tenor);
      await tapIn(tester, muteIn(tenor));
      expect(harness.engine.volumes[VoicePart.tenor], 0);
      expect(sliderValue(tester, tenor), level);

      // Moving a muted voice's slider stays silent (Mute is independent).
      await setSlider(tester, tenor, 0.75);
      final moved = sliderValue(tester, tenor);
      expect(harness.engine.volumes[VoicePart.tenor], 0);

      await tapIn(tester, muteIn(tenor));
      expect(harness.engine.volumes[VoicePart.tenor], moved);
    });

    testWidgets('a muted slider at zero is still muted, not "unmuted at 0"', (
      tester,
    ) async {
      await pumpPlayback(tester, ready());
      await openMixer(tester);
      final bass = voiceRow(VoicePart.bass);
      await tapIn(tester, muteIn(bass));
      await setSlider(tester, bass, 0);
      expect(
        controller(tester).state.muted,
        contains(VoicePart.bass),
        reason: 'mute state independent of slider position',
      );
    });
  });

  group('solo', () {
    testWidgets('only soloed rows sound; Mute wins over Solo', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await openMixer(tester);
      final volumes = harness.engine.volumes;

      await tapIn(tester, soloIn(voiceRow(VoicePart.alto)));
      expect(volumes, {
        VoicePart.soprano: 0,
        VoicePart.alto: 1,
        VoicePart.tenor: 0,
        VoicePart.bass: 0,
      });

      await tapIn(tester, soloIn(voiceRow(VoicePart.bass)));
      expect(volumes[VoicePart.alto], 1);
      expect(volumes[VoicePart.bass], 1);
      expect(volumes[VoicePart.soprano], 0);

      await tapIn(tester, muteIn(voiceRow(VoicePart.alto)));
      expect(volumes[VoicePart.alto], 0);
      expect(volumes[VoicePart.bass], 1);

      await tapIn(tester, soloIn(voiceRow(VoicePart.alto)));
      await tapIn(tester, soloIn(voiceRow(VoicePart.bass)));
      expect(volumes[VoicePart.soprano], 1);
      expect(volumes[VoicePart.alto], 0, reason: 'still muted');
      expect(volumes[VoicePart.tenor], 1);
    });

    testWidgets('mixer level stacks with the Playback voice chips', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      final c = controller(tester);
      c.setVoiceVolume(VoicePart.soprano, 0.5);
      expect(harness.engine.volumes[VoicePart.soprano], 0.5);
      c.toggleVoice(VoicePart.soprano);
      expect(harness.engine.volumes[VoicePart.soprano], 0);
      c.toggleVoice(VoicePart.soprano);
      expect(harness.engine.volumes[VoicePart.soprano], 0.5);
      // A deselected chip stays silent even when soloed.
      c
        ..toggleVoice(VoicePart.alto)
        ..setVoiceSoloed(VoicePart.alto, soloed: true);
      expect(harness.engine.volumes[VoicePart.alto], 0);
      expect(harness.engine.volumes[VoicePart.soprano], 0);
    });
  });

  group('metronome row', () {
    testWidgets('level, mute and solo apply once the Speed toggle is on', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      final engine = harness.engine;
      controller(tester).setMetronomeOn(on: true);
      expect(engine.clickVolume, 1);
      await openMixer(tester);

      await setSlider(tester, metronomeRow, 0.5);
      final level = sliderValue(tester, metronomeRow);
      expect(engine.clickVolume, level);

      await tapIn(tester, muteIn(metronomeRow));
      expect(engine.clickVolume, 0);
      expect(sliderValue(tester, metronomeRow), level);
      await tapIn(tester, muteIn(metronomeRow));
      expect(engine.clickVolume, level);

      // Soloing a voice silences the click; soloing the click, the voices.
      await tapIn(tester, soloIn(voiceRow(VoicePart.soprano)));
      expect(engine.clickVolume, 0);
      await tapIn(tester, soloIn(voiceRow(VoicePart.soprano)));
      await tapIn(tester, soloIn(metronomeRow));
      expect(engine.clickVolume, level);
      expect(engine.volumes.values.every((v) => v == 0), isTrue);

      // The mixer row never turns the click on by itself.
      controller(tester).setMetronomeOn(on: false);
      expect(engine.clickVolume, 0);
    });

    testWidgets('a click that fails mid-play disables its row, with a note; '
        'the voices keep playing', (tester) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await openMixer(tester);
      await tapIn(tester, soloIn(metronomeRow));

      harness.engine.failClick();
      await tester.pump();
      expect(find.text(PlaybackMessages.metronomeUnavailable), findsOneWidget);
      expect(tester.widget<Slider>(sliderIn(metronomeRow)).onChanged, isNull);
      expect(
        tester.widget<SheetCheckbox>(soloIn(metronomeRow)).onChanged,
        isNull,
      );
      // The click's solo is dropped so the voices aren't left silent.
      expect(harness.engine.volumes.values.every((v) => v == 1), isTrue);
      expect(harness.engine.clickVolume, 0);
      expect(harness.engine.playing, isTrue);
      // Voice rows are untouched.
      expect(
        tester.widget<Slider>(sliderIn(voiceRow(VoicePart.alto))).onChanged,
        isNotNull,
      );
    });

    for (final (name, harness) in [
      ('cannot be written', () => ready(clickWriteError: StateError('disk'))),
      ('will not load', () => ready(clickAttachFails: true)),
    ]) {
      testWidgets('a click that $name: row disabled, voices play', (
        tester,
      ) async {
        final h = harness();
        await pumpPlayback(tester, h);
        await openMixer(tester);
        expect(
          find.text(PlaybackMessages.metronomeUnavailable),
          findsOneWidget,
        );
        expect(tester.widget<Slider>(sliderIn(metronomeRow)).onChanged, isNull);
        expect(h.engine.volumes.values.every((v) => v == 1), isTrue);
        expect(find.text(kTitle), findsOneWidget);
      });
    }
  });

  testWidgets('a voice that failed to load keeps a disabled row', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    final harness = ready(failAtLoad: {VoicePart.alto});
    await pumpPlayback(tester, harness);
    await openMixer(tester);
    final alto = voiceRow(VoicePart.alto);
    expect(alto, findsOneWidget);
    expect(tester.widget<Slider>(sliderIn(alto)).onChanged, isNull);
    expect(tester.widget<SheetCheckbox>(soloIn(alto)).onChanged, isNull);
    expect(
      find.bySemanticsLabel(
        PlaybackMessages.rowUnavailable(VoicePart.alto.label),
      ),
      findsOneWidget,
    );
    await tester.tap(muteIn(alto), warnIfMissed: false);
    await tester.pump();
    expect(controller(tester).state.muted, isEmpty);
    expect(
      tester.widget<Slider>(sliderIn(voiceRow(VoicePart.soprano))).onChanged,
      isNotNull,
    );
    handle.dispose();
  });

  group('session (AC6, AC7)', () {
    testWidgets('X closes onto Playback; music and seek bar never stop', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await openMixer(tester);

      // The seek bar keeps moving under the sheet.
      final before = positionText(tester);
      await tester.pump(const Duration(milliseconds: 1500));
      expect(positionText(tester), isNot(before));

      await tester.tap(find.byTooltip(PlaybackMessages.close));
      await settle(tester);
      expect(find.byKey(const ValueKey('mixer-sheet')), findsNothing);
      expect(harness.engine.playing, isTrue);
      expect(harness.engine.pauseCalls, 0);
      expect(find.text(kTitle), findsOneWidget);
    });

    testWidgets('settings last while Playback is open, reset on reopen', (
      tester,
    ) async {
      final harness = ready();
      await pumpPlayback(tester, harness);
      await openMixer(tester);
      await setSlider(tester, voiceRow(VoicePart.soprano), 0.3);
      await tapIn(tester, muteIn(voiceRow(VoicePart.bass)));
      await tapIn(tester, soloIn(voiceRow(VoicePart.alto)));
      final level = sliderValue(tester, voiceRow(VoicePart.soprano));
      await tester.tap(find.byTooltip(PlaybackMessages.close));
      await settle(tester);

      // Same session: reopening the sheet shows the same settings.
      await openMixer(tester);
      expect(sliderValue(tester, voiceRow(VoicePart.soprano)), level);
      expect(
        tester.widget<SheetCheckbox>(soloIn(voiceRow(VoicePart.alto))).value,
        isTrue,
      );
      await tester.tap(find.byTooltip(PlaybackMessages.close));
      await settle(tester);

      // Leave the score and open it again: defaults.
      await tester.tap(find.byTooltip(PlaybackMessages.back));
      await settle(tester);
      await tester.pump(const Duration(seconds: 1));
      expect(harness.engines.single.disposed, isTrue);
      await reopenPlayback(tester);
      expect(harness.engines, hasLength(2));
      expect(harness.engine.volumes.values.every((v) => v == 1), isTrue);
      await openMixer(tester);
      for (final voice in VoicePart.values) {
        expect(sliderValue(tester, voiceRow(voice)), 1);
        expect(
          tester.widget<SheetCheckbox>(soloIn(voiceRow(voice))).value,
          isFalse,
        );
      }
      expect(controller(tester).state.muted, isEmpty);
    });
  });

  group('layout and accessibility', () {
    for (final (name, size, scale) in [
      ('360 dp', const Size(360, 640), 1.0),
      ('320 dp', const Size(320, 568), 1.0),
      ('360 dp at 1.3x text', const Size(360, 740), 1.3),
      ('412 dp at 2x text', const Size(412, 917), 2.0),
    ]) {
      testWidgets('fits without overflow: $name', (tester) async {
        await pumpPlayback(tester, ready(), size: size, textScale: scale);
        await openMixer(tester);
        expect(tester.takeException(), isNull);
        for (final voice in VoicePart.values) {
          final r = tester.getRect(soloIn(voiceRow(voice)));
          expect(r.width, greaterThanOrEqualTo(48));
          expect(r.height, greaterThanOrEqualTo(48));
          expect(
            tester.getSize(sliderIn(voiceRow(voice))).width,
            greaterThan(100),
          );
        }
      });
    }

    testWidgets('meets the tap-target, label and contrast guidelines', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await pumpPlayback(tester, ready());
      await openMixer(tester);
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      handle.dispose();
    });
  });
}
