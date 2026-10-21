import 'dart:async';
import 'dart:ui' show CheckedState, Tristate;

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/export_selection.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/export_messages.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';
import 'package:piyanota_application/services/export_service.dart';
import 'package:piyanota_application/state/export_providers.dart';
import 'package:piyanota_application/state/playback_providers.dart';
import 'package:piyanota_application/widgets/primary_pill_button.dart';

import '../playback/playback_fakes.dart';
import 'export_fakes.dart';

/// PIYA-211 Export Audio modal, over a real Playback screen with fake
/// audio and a fake device channel.
void main() {
  PlaybackHarness harness(
    FakeExportService service, {
    bool tempoKnown = true,
    int tempoBpm = 90,
    Set<VoicePart> failAtLoad = const {},
  }) => PlaybackHarness(
    ScriptedScoreResultApi([
      testResult(tempoKnown: tempoKnown, tempoBpm: tempoBpm),
    ], timing: testTiming()),
    engineFailAtLoad: failAtLoad,
    exportService: service,
  );

  Finder row(String name) => find.byKey(ValueKey('export-row-$name'));
  Finder box(String label) => find.bySemanticsLabel(label);
  final download = find.byKey(const ValueKey('export-download'));
  final sheet = find.byKey(const ValueKey('export-sheet'));

  PlaybackController controller(WidgetTester tester) =>
      appContainer(tester).read(playbackControllerProvider(kScoreId).notifier);
  PlaybackState playback(WidgetTester tester) =>
      appContainer(tester).read(playbackControllerProvider(kScoreId));

  Future<void> tick(WidgetTester tester, String label) async {
    await tester.tap(box(label));
    await tester.pump();
  }

  SemanticsData semanticsOf(WidgetTester tester, String label) =>
      tester.getSemantics(box(label)).getSemanticsData();
  // What TalkBack announces (AC21), not just how the box looks.
  bool isChecked(WidgetTester tester, String label) =>
      semanticsOf(tester, label).flagsCollection.isChecked ==
      CheckedState.isTrue;
  bool isEnabled(WidgetTester tester, String label) =>
      semanticsOf(tester, label).flagsCollection.isEnabled == Tristate.isTrue;

  /// Opens the sheet; with [clear], unticks what it opened with so a test
  /// starts from nothing ticked.
  Future<void> openExport(WidgetTester tester, {bool clear = true}) async {
    await tester.tap(find.byTooltip(PlaybackMessages.download));
    await settle(tester);
    expect(sheet, findsOneWidget);
    if (!clear) return;
    for (final label in [
      for (final voice in VoicePart.values) ExportMessages.voiceBox(voice),
      ExportMessages.clickBox,
    ]) {
      if (isChecked(tester, label)) await tick(tester, label);
    }
  }

  Set<VoicePart> tickedVoices(WidgetTester tester) => {
    for (final voice in VoicePart.values)
      if (isChecked(tester, ExportMessages.voiceBox(voice))) voice,
  };

  Map<String, double> gains(ExportJob job) => {
    for (final input in job.inputs) input.track.pathSegments.last: input.gain,
  };

  bool downloadEnabled(WidgetTester tester) =>
      tester.widget<PrimaryPillButton>(download).onPressed != null;

  group('selection (AC2-AC8)', () {
    testWidgets('opens with the voices Playback plays ticked, and the '
        'click unticked while the metronome is off', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      expect(playback(tester).selected, VoicePart.values.toSet());
      expect(playback(tester).metronomeOn, isFalse);
      await openExport(tester, clear: false);

      expect(find.text(ExportMessages.title), findsOneWidget);
      for (final voice in VoicePart.values) {
        expect(row(voice.name), findsOneWidget);
      }
      expect(tickedVoices(tester), VoicePart.values.toSet());
      expect(isChecked(tester, ExportMessages.allVoicesBox), isTrue);
      expect(find.text(ExportMessages.allVoices), findsOneWidget);
      expect(find.text(ExportMessages.withClick), findsOneWidget);
      expect(isChecked(tester, ExportMessages.clickBox), isFalse);
      expect(downloadEnabled(tester), isTrue);
    });

    testWidgets('with nothing ticked Download is disabled', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      await openExport(tester);
      expect(tickedVoices(tester), isEmpty);
      expect(downloadEnabled(tester), isFalse);
    });

    testWidgets('All Voices ticks every voice, and unticks them', (
      tester,
    ) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      await openExport(tester);

      await tick(tester, ExportMessages.allVoicesBox);
      for (final voice in VoicePart.values) {
        expect(
          isChecked(tester, ExportMessages.voiceBox(voice)),
          isTrue,
          reason: voice.name,
        );
      }
      expect(downloadEnabled(tester), isTrue);

      await tick(tester, ExportMessages.allVoicesBox);
      expect(downloadEnabled(tester), isFalse);
    });

    testWidgets('unticking one voice clears All Voices; ticking each sets '
        'it', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      await openExport(tester);

      for (final voice in VoicePart.values) {
        await tick(tester, ExportMessages.voiceBox(voice));
      }
      expect(isChecked(tester, ExportMessages.allVoicesBox), isTrue);
      await tick(tester, ExportMessages.voiceBox(VoicePart.alto));
      expect(isChecked(tester, ExportMessages.allVoicesBox), isFalse);
    });

    testWidgets('the click alone does not enable Download', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      await openExport(tester);

      await tick(tester, ExportMessages.clickBox);
      expect(isChecked(tester, ExportMessages.clickBox), isTrue);
      expect(downloadEnabled(tester), isFalse);
    });

    testWidgets('an unavailable voice is disabled and says why; All '
        'Voices means the available ones (Review Focus 4)', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(
        tester,
        harness(service, failAtLoad: {VoicePart.tenor}),
      );
      // The failed-voice alert comes up first.
      await tester.tap(find.text(PlaybackMessages.ok));
      await tester.pumpAndSettle();
      await openExport(tester);

      expect(
        isEnabled(tester, ExportMessages.voiceBox(VoicePart.tenor)),
        isFalse,
      );
      expect(
        find.text(ExportMessages.voiceUnavailable(VoicePart.tenor)),
        findsOneWidget,
      );
      await tick(tester, ExportMessages.allVoicesBox);
      await tester.tap(download);
      await settle(tester);

      final (job, _) = service.exports.single;
      expect(job.inputs.map((i) => i.track.pathSegments.last), [
        'soprano.mp3',
        'alto.mp3',
        'bass.mp3',
      ]);
      expect(job.fileName, 'Bituin Walang Ningning_AllVoices.mp3');
    });

    testWidgets('no tempo: the click row is disabled with the Speed '
        "sheet's note (Review Focus 5)", (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service, tempoKnown: false));
      await openExport(tester);

      expect(isEnabled(tester, ExportMessages.clickBox), isFalse);
      expect(find.text(PlaybackMessages.metronomeNeedsTempo), findsOneWidget);
    });
  });

  group('closing (AC9, AC11)', () {
    for (final (name, close) in <(String, Future<void> Function(WidgetTester))>[
      ('X', (t) => t.tap(find.byTooltip(PlaybackMessages.close))),
      ('scrim', (t) => t.tapAt(const Offset(200, 40))),
      (
        'back',
        (t) async {
          await t.binding.handlePopRoute();
        },
      ),
    ]) {
      testWidgets('$name closes without exporting', (tester) async {
        final service = FakeExportService();
        await pumpPlayback(tester, harness(service));
        await openExport(tester);
        await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));

        await close(tester);
        await settle(tester);
        expect(sheet, findsNothing);
        expect(service.pickCalls, 0);
        expect(service.exports, isEmpty);
      });
    }

    testWidgets('cancelling the folder picker keeps the sheet and ticks', (
      tester,
    ) async {
      final service = FakeExportService(folder: null);
      await pumpPlayback(tester, harness(service));
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.bass));

      await tester.tap(download);
      await settle(tester);
      expect(sheet, findsOneWidget);
      expect(service.exports, isEmpty);
      expect(
        isChecked(tester, ExportMessages.voiceBox(VoicePart.bass)),
        isTrue,
      );
      expect(downloadEnabled(tester), isTrue);
    });
  });

  group('busy (AC12)', () {
    testWidgets('shows "Preparing audio…" and cannot be closed', (
      tester,
    ) async {
      final service = FakeExportService()..exportGate = Completer<void>();
      await pumpPlayback(tester, harness(service));
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));

      await tester.tap(download);
      await tester.pump();
      expect(find.text(ExportMessages.preparing), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(
        isEnabled(tester, ExportMessages.voiceBox(VoicePart.alto)),
        isFalse,
      );

      await tester.tap(find.byTooltip(PlaybackMessages.close));
      await tester.tapAt(const Offset(200, 40));
      await tester.binding.handlePopRoute();
      await settle(tester);
      expect(sheet, findsOneWidget);

      // A second tap while busy starts nothing.
      await tester.tap(download, warnIfMissed: false);
      await tester.pump();
      expect(service.exports, hasLength(1));

      service.exportGate!.complete();
      await settle(tester);
      expect(sheet, findsNothing);
    });
  });

  group('success (AC16)', () {
    testWidgets('closes the sheet and shows the name and folder', (
      tester,
    ) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));
      await tester.tap(download);
      await settle(tester);

      expect(sheet, findsNothing);
      expect(find.text(ExportMessages.successTitle), findsOneWidget);
      expect(find.textContaining(kSaved.fileName), findsOneWidget);
      expect(find.textContaining(kSaved.location), findsOneWidget);
      expect(service.exports.single.$2, kTreeUri);

      await tester.tap(find.text(ExportMessages.openFolder));
      await tester.pump();
      expect(service.opened, [kTreeUri]);

      await tester.tap(find.text(ExportMessages.ok));
      await settle(tester);
      expect(find.text(ExportMessages.successTitle), findsNothing);
    });

    testWidgets('Open folder goes away when no app can open it', (
      tester,
    ) async {
      final service = FakeExportService(canOpen: false);
      await pumpPlayback(tester, harness(service));
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));
      await tester.tap(download);
      await settle(tester);

      await tester.tap(find.text(ExportMessages.openFolder));
      await tester.pump();
      expect(find.text(ExportMessages.openFolder), findsNothing);
      expect(find.text(ExportMessages.ok), findsOneWidget);
    });
  });

  group('failures (AC18, AC20)', () {
    for (final (failure, message) in <(ExportFailure, String)>[
      (const StorageFull(), ExportMessages.storageFull),
      (const PermissionDenied(), ExportMessages.permissionDenied),
      (const GenerationFailed(), ExportMessages.generationFailed),
      (const Interrupted(), ExportMessages.interrupted),
    ]) {
      testWidgets('${failure.runtimeType} shows its message and Retry', (
        tester,
      ) async {
        final service = FakeExportService(failures: [failure]);
        await pumpPlayback(tester, harness(service));
        await openExport(tester);
        await tick(tester, ExportMessages.voiceBox(VoicePart.alto));
        await tester.tap(download);
        await settle(tester);

        expect(sheet, findsOneWidget);
        expect(find.text(message), findsOneWidget);
        expect(
          isChecked(tester, ExportMessages.voiceBox(VoicePart.alto)),
          isTrue,
        );

        await tester.tap(find.text(ExportMessages.retry));
        await settle(tester);
        expect(service.exports, hasLength(2));
        expect(find.text(ExportMessages.successTitle), findsOneWidget);
        // Only a folder the app may not write to is asked for again.
        expect(service.pickCalls, failure is PermissionDenied ? 2 : 1);
      });
    }

    testWidgets('the click failing to render is "couldn\'t be made"', (
      tester,
    ) async {
      final service = FakeExportService();
      await pumpPlayback(
        tester,
        PlaybackHarness(
          ScriptedScoreResultApi([testResult()], timing: testTiming()),
          exportService: service,
          clickWriteError: const FileSystemExceptionStub(),
        ),
      );
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.alto));
      await tick(tester, ExportMessages.clickBox);
      await tester.tap(download);
      await settle(tester);

      expect(find.text(ExportMessages.generationFailed), findsOneWidget);
      expect(service.exports, isEmpty);
    });
  });

  group('mix copies Playback (AC7, AC23)', () {
    testWidgets('speed is chosen / score tempo: 60 of 80 is 0.75 (Review '
        'Focus 2)', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service, tempoBpm: 80));
      controller(tester).setBpm(60);
      final state = playback(tester);

      final job = buildExportJob(
        state,
        ExportSelection.empty(state.available).toggleAll(),
        kTitle,
      );
      expect(job.speed, 0.75);
    });

    testWidgets('gains: a voice the Mixer lets be heard keeps its level; '
        'a muted, soloed-out or zeroed one gets the default level', (
      tester,
    ) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester)
        ..setVoiceVolume(VoicePart.soprano, 0.5)
        ..setVoiceVolume(VoicePart.alto, 0)
        ..setVoiceVolume(VoicePart.bass, 0.3)
        ..setVoiceMuted(VoicePart.bass, muted: true);
      final all = ExportSelection.empty(playback(tester).available).toggleAll();

      expect(gains(buildExportJob(playback(tester), all, kTitle)), {
        'soprano.mp3': 0.5,
        'alto.mp3': exportDefaultLevel,
        'tenor.mp3': 1.0,
        'bass.mp3': exportDefaultLevel,
      });

      controller(tester)
        ..setVoiceVolume(VoicePart.tenor, 0.7)
        ..setVoiceSoloed(VoicePart.tenor, soloed: true);
      expect(gains(buildExportJob(playback(tester), all, kTitle)), {
        'soprano.mp3': exportDefaultLevel,
        'alto.mp3': exportDefaultLevel,
        'tenor.mp3': 0.7,
        'bass.mp3': exportDefaultLevel,
      });
      expect(exportDefaultLevel, PlaybackController.fullVolume);
    });

    testWidgets('a voice ticked with its chip off keeps its Mixer level', (
      tester,
    ) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester)
        ..setVoiceVolume(VoicePart.alto, 0.4)
        ..toggleVoice(VoicePart.alto);
      expect(playback(tester).selected.contains(VoicePart.alto), isFalse);
      final alto = ExportSelection.empty(playback(tester).available)
          .toggleVoice(VoicePart.alto);
      expect(gains(buildExportJob(playback(tester), alto, kTitle)), {
        'alto.mp3': 0.4,
      });
    });

    testWidgets('click gain: its Mixer level, or the default click level '
        'when muted or soloed out by a voice', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      final click = Uri.parse('test://export-click.wav');
      final voices = ExportSelection.empty(playback(tester).available)
          .toggleVoice(VoicePart.soprano)
          .toggleClick();
      double clickGain() => buildExportJob(
        playback(tester),
        voices,
        kTitle,
        clickTrack: click,
      ).inputs.last.gain;

      controller(tester)
        ..setMetronomeOn(on: true)
        ..setClickVolume(0.25);
      expect(clickGain(), 0.25);

      controller(tester).setClickMuted(muted: true);
      expect(clickGain(), exportDefaultClickLevel);

      controller(tester)
        ..setClickMuted(muted: false)
        ..setVoiceSoloed(VoicePart.soprano, soloed: true);
      expect(clickGain(), exportDefaultClickLevel);

      controller(tester).setClickSoloed(soloed: true);
      expect(clickGain(), 0.25);
    });

    testWidgets('voices unticked here are left out even if Playback plays '
        'them', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      final state = playback(tester);
      final job = buildExportJob(
        state,
        ExportSelection.empty(state.available).toggleVoice(VoicePart.tenor),
        kTitle,
      );
      expect(job.inputs.single.track.pathSegments.last, 'tenor.mp3');
      expect(job.fileName, 'Bituin Walang Ningning_Tenor.mp3');
    });

    testWidgets('the click is in only when ticked, at the Mixer level, '
        'even with the Speed toggle off', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester)
        ..setMetronomeOn(on: false)
        ..setClickVolume(0.25);
      final click = Uri.parse('test://export-click.wav');
      final voices = ExportSelection.empty(playback(tester).available)
          .toggleVoice(VoicePart.soprano);

      final without = buildExportJob(
        playback(tester),
        voices,
        kTitle,
        clickTrack: click,
      );
      expect(without.inputs.map((i) => i.track), isNot(contains(click)));

      final withClick = buildExportJob(
        playback(tester),
        voices.toggleClick(),
        kTitle,
        clickTrack: click,
      );
      expect(withClick.inputs.last, (track: click, gain: 0.25));
      expect(withClick.fileName, 'Bituin Walang Ningning_Soprano_Click.mp3');
    });

    testWidgets('Download with the click ticked plans a fresh click and '
        'sends it', (tester) async {
      final service = FakeExportService();
      final plansBefore = <int>[];
      final h = harness(service);
      await pumpPlayback(tester, h);
      plansBefore.add(h.clickPlans.length);
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));
      await tick(tester, ExportMessages.clickBox);
      await tester.tap(download);
      await settle(tester);

      expect(h.clickPlans.length, plansBefore.single + 1);
      final (job, _) = service.exports.single;
      expect(job.inputs.last.track, Uri.parse('test://click.wav'));
    });
  });

  group('pre-selection follows Playback (user decision 2026-10-21)', () {
    testWidgets('a voice with its chip off starts unticked', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester).toggleVoice(VoicePart.tenor);
      await openExport(tester, clear: false);
      expect(tickedVoices(tester), {
        VoicePart.soprano,
        VoicePart.alto,
        VoicePart.bass,
      });
      expect(isChecked(tester, ExportMessages.allVoicesBox), isFalse);
    });

    testWidgets('muted and volume-0 voices start unticked; ticked, they '
        'export at the default level, with no muted note', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester)
        ..setVoiceMuted(VoicePart.alto, muted: true)
        ..setVoiceVolume(VoicePart.bass, 0);
      await openExport(tester, clear: false);
      expect(tickedVoices(tester), {VoicePart.soprano, VoicePart.tenor});

      await tick(tester, ExportMessages.allVoicesBox);
      expect(tickedVoices(tester), VoicePart.values.toSet());
      expect(find.text('Muted in Voice Mixer'), findsNothing);
      await tester.tap(download);
      await settle(tester);
      expect(gains(service.exports.single.$1), {
        'soprano.mp3': 1.0,
        'alto.mp3': exportDefaultLevel,
        'tenor.mp3': 1.0,
        'bass.mp3': exportDefaultLevel,
      });
    });

    testWidgets('a solo ticks only the soloed voices; the click is soloed '
        'out too', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester)
        ..setMetronomeOn(on: true)
        ..setVoiceSoloed(VoicePart.alto, soloed: true);
      await openExport(tester, clear: false);
      expect(tickedVoices(tester), {VoicePart.alto});
      expect(isChecked(tester, ExportMessages.clickBox), isFalse);
    });

    testWidgets('metronome on: the click starts ticked', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester).setMetronomeOn(on: true);
      await openExport(tester, clear: false);
      expect(isChecked(tester, ExportMessages.clickBox), isTrue);
    });

    testWidgets('metronome on but muted in the Mixer: the click starts '
        'unticked', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester)
        ..setMetronomeOn(on: true)
        ..setClickMuted(muted: true);
      await openExport(tester, clear: false);
      expect(isChecked(tester, ExportMessages.clickBox), isFalse);
    });

    testWidgets('a soloed click leaves the voices unticked, so Download '
        'waits for a voice; one ticked exports at the default level', (
      tester,
    ) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester)
        ..setMetronomeOn(on: true)
        ..setVoiceVolume(VoicePart.soprano, 0.6)
        ..setClickSoloed(soloed: true);
      await openExport(tester, clear: false);
      expect(tickedVoices(tester), isEmpty);
      expect(isChecked(tester, ExportMessages.clickBox), isTrue);
      expect(downloadEnabled(tester), isFalse);

      await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));
      await tester.tap(download);
      await settle(tester);
      final (job, _) = service.exports.single;
      expect(job.inputs.first.gain, exportDefaultLevel);
      expect(job.inputs.length, 2);
    });

    testWidgets('ticks in the sheet never change the Mixer, the Speed '
        'toggle or the chips', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester)
        ..toggleVoice(VoicePart.tenor)
        ..setVoiceMuted(VoicePart.alto, muted: true);
      final before = playback(tester);
      await openExport(tester, clear: false);
      await tick(tester, ExportMessages.voiceBox(VoicePart.tenor));
      await tick(tester, ExportMessages.voiceBox(VoicePart.alto));
      await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));
      await tick(tester, ExportMessages.clickBox);
      await tick(tester, ExportMessages.allVoicesBox);
      final after = playback(tester);
      expect(after.selected, before.selected);
      expect(after.muted, before.muted);
      expect(after.soloed, before.soloed);
      expect(after.volumes, before.volumes);
      expect(after.metronomeOn, before.metronomeOn);
      expect(after.clickMuted, before.clickMuted);
      expect(after.clickSoloed, before.clickSoloed);
    });

    testWidgets('the Speed toggle and the Mixer metronome row are one '
        'state, and the sheet starts from it', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      final mixerOffNote = find.byKey(const ValueKey('mixer-metronome-off'));

      await tester.tap(find.bySemanticsLabel(PlaybackMessages.voiceMixer));
      await settle(tester);
      expect(mixerOffNote, findsOneWidget);
      await tester.tap(find.byTooltip(PlaybackMessages.close));
      await settle(tester);

      await tester.tap(find.bySemanticsLabel(PlaybackMessages.speed));
      await settle(tester);
      await tester.tap(find.byKey(const ValueKey('metronome-toggle')));
      await settle(tester);
      await tester.tap(find.byTooltip(PlaybackMessages.close));
      await settle(tester);
      expect(playback(tester).metronomeOn, isTrue);

      await tester.tap(find.bySemanticsLabel(PlaybackMessages.voiceMixer));
      await settle(tester);
      expect(mixerOffNote, findsNothing);
      await tester.tap(find.byTooltip(PlaybackMessages.close));
      await settle(tester);

      await openExport(tester, clear: false);
      expect(isChecked(tester, ExportMessages.clickBox), isTrue);
    });
  });

  group('cancel and progress', () {
    final cancelButton = find.byKey(const ValueKey('export-cancel'));
    final bar = find.byKey(const ValueKey('export-progress'));

    testWidgets('the bar follows the render, Cancel stops it, nothing is '
        'saved and the sheet says so calmly', (tester) async {
      final service = FakeExportService()..exportGate = Completer<void>();
      await pumpPlayback(tester, harness(service));
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));
      expect(cancelButton, findsNothing);

      await tester.tap(download);
      await tester.pump();
      expect(bar, findsOneWidget);
      expect(tester.widget<LinearProgressIndicator>(bar).value, isNull);
      service.lastOnProgress!(0.4);
      await tester.pump();
      expect(tester.widget<LinearProgressIndicator>(bar).value, 0.4);

      // Still non-dismissible: Cancel is the way out.
      await tester.binding.handlePopRoute();
      await tester.pump();
      expect(sheet, findsOneWidget);

      await tester.tap(cancelButton);
      await tester.pump();
      expect(service.lastCancel!.isCancelled, isTrue);
      await settle(tester);

      expect(sheet, findsOneWidget);
      expect(find.text(ExportMessages.cancelled), findsOneWidget);
      expect(find.byKey(const ValueKey('export-error')), findsNothing);
      expect(find.text(ExportMessages.successTitle), findsNothing);
      expect(bar, findsNothing);
      expect(cancelButton, findsNothing);
      expect(
        isChecked(tester, ExportMessages.voiceBox(VoicePart.soprano)),
        isTrue,
      );
      expect(downloadEnabled(tester), isTrue);
    });

    testWidgets('after a cancel, the next Download is a fresh export with '
        'its own Cancel', (tester) async {
      final service = FakeExportService()..exportGate = Completer<void>();
      await pumpPlayback(tester, harness(service));
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.alto));
      await tester.tap(download);
      await tester.pump();
      await tester.tap(cancelButton);
      await settle(tester);
      final first = service.lastCancel!;

      service.exportGate = null;
      await tester.tap(download);
      await settle(tester);
      expect(service.exports, hasLength(2));
      expect(service.lastCancel, isNot(same(first)));
      expect(service.lastCancel!.isCancelled, isFalse);
      expect(find.text(ExportMessages.successTitle), findsOneWidget);
    });
  });

  group('review findings', () {
    testWidgets('M1: a voice failing while the sheet is open is unticked '
        'live, and the file names only the voices exported', (tester) async {
      final service = FakeExportService();
      final h = harness(service);
      await pumpPlayback(tester, h);
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));
      await tick(tester, ExportMessages.voiceBox(VoicePart.alto));

      h.engine.fail(VoicePart.alto);
      await tester.pump();
      await tester.pump();

      expect(
        isEnabled(tester, ExportMessages.voiceBox(VoicePart.alto)),
        isFalse,
      );
      expect(
        isChecked(tester, ExportMessages.voiceBox(VoicePart.alto)),
        isFalse,
      );
      expect(
        find.text(ExportMessages.voiceUnavailable(VoicePart.alto)),
        findsOneWidget,
      );
      // Dismiss the failed-voice alert Playback raises underneath.
      if (find.text(PlaybackMessages.ok).evaluate().isNotEmpty) {
        await tester.tap(find.text(PlaybackMessages.ok));
        await tester.pumpAndSettle();
      }
      await tester.tap(download);
      await settle(tester);
      final (job, _) = service.exports.single;
      expect(job.inputs.map((i) => i.track.pathSegments.last), ['soprano.mp3']);
      expect(job.fileName, 'Bituin Walang Ningning_Soprano.mp3');
    });

    testWidgets('M1: the only ticked voice failing while the sheet is '
        'open disables Download', (tester) async {
      final service = FakeExportService();
      final h = harness(service);
      await pumpPlayback(tester, h);
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.tenor));
      expect(downloadEnabled(tester), isTrue);

      h.engine.fail(VoicePart.tenor);
      await tester.pump();
      await tester.pump();
      expect(downloadEnabled(tester), isFalse);
    });

    testWidgets('M1: the only ticked voice failing during the folder pick '
        'makes nothing, not a click-only file', (tester) async {
      final service = FakeExportService();
      final h = harness(service);
      await pumpPlayback(tester, h);
      final plansBefore = h.clickPlans.length;
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.tenor));
      await tick(tester, ExportMessages.clickBox);
      service.onPick = () async {
        h.engine.fail(VoicePart.tenor);
        await Future<void>.delayed(Duration.zero);
      };

      await tester.tap(download);
      await settle(tester);
      expect(service.exports, isEmpty);
      expect(h.clickPlans.length, plansBefore);
      // L-c: Retry cannot help, so the banner says why and offers none.
      expect(find.text(ExportMessages.nothingToExport), findsOneWidget);
      expect(find.text(ExportMessages.generationFailed), findsNothing);
      expect(find.text(ExportMessages.retry), findsNothing);
      expect(find.text(ExportMessages.successTitle), findsNothing);

      // L-c: a new tick makes "nothing to export" stale, so it goes.
      if (find.text(PlaybackMessages.ok).evaluate().isNotEmpty) {
        await tester.tap(find.text(PlaybackMessages.ok));
        await tester.pumpAndSettle();
      }
      await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));
      expect(find.text(ExportMessages.nothingToExport), findsNothing);
      expect(find.byKey(const ValueKey('export-error')), findsNothing);
    });

    testWidgets('M1: buildExportJob leaves out a ticked voice that has '
        'since failed, and names only the rest', (tester) async {
      final service = FakeExportService();
      final h = harness(service);
      await pumpPlayback(tester, h);
      final stale = ExportSelection.empty(playback(tester).available)
          .toggleVoice(VoicePart.soprano)
          .toggleVoice(VoicePart.alto);
      h.engine.fail(VoicePart.alto);
      await tester.pump();
      await tester.pump();

      final job = buildExportJob(playback(tester), stale, kTitle);
      expect(job.inputs.single.track.pathSegments.last, 'soprano.mp3');
      expect(job.fileName, 'Bituin Walang Ningning_Soprano.mp3');
    });

    testWidgets('M1: buildExportJob with no voice left fails, even with '
        'the click', (tester) async {
      final service = FakeExportService();
      final h = harness(service);
      await pumpPlayback(tester, h);
      final stale = ExportSelection.empty(playback(tester).available)
          .toggleVoice(VoicePart.alto)
          .toggleClick();
      h.engine.fail(VoicePart.alto);
      await tester.pump();
      await tester.pump();

      expect(
        () => buildExportJob(
          playback(tester),
          stale,
          kTitle,
          clickTrack: Uri.parse('test://click.wav'),
        ),
        throwsA(isA<GenerationFailed>()),
      );
    });

    test('M4: the folder message names only what the user can do', () {
      expect(
        ExportMessages.permissionDenied,
        'PiyaNota can\u2019t save to that folder. Choose another folder and '
        'try again.',
      );
      expect(ExportMessages.permissionDenied, isNot(contains('Settings')));
    });

    testWidgets('M4: no folder picker on the phone has its own message', (
      tester,
    ) async {
      final service = FakeExportService(pickFailure: const NoFolderPicker());
      await pumpPlayback(tester, harness(service));
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.soprano));
      await tester.tap(download);
      await settle(tester);

      expect(find.text(ExportMessages.noFolderPicker), findsOneWidget);
      expect(find.text(ExportMessages.permissionDenied), findsNothing);
      expect(service.exports, isEmpty);
    });

    testWidgets('L10: Playback failing during an export that then fails '
        'closes the sheet once it is no longer busy', (tester) async {
      final service = FakeExportService(failures: const [GenerationFailed()])
        ..exportGate = Completer<void>();
      final h = PlaybackHarness(
        ScriptedScoreResultApi([testResult()], timing: testTiming()),
        engineFailAtLoad: {VoicePart.soprano, VoicePart.alto, VoicePart.tenor},
        exportService: service,
      );
      await pumpPlayback(tester, h);
      await tester.tap(find.text(PlaybackMessages.ok));
      await tester.pumpAndSettle();
      await openExport(tester);
      await tick(tester, ExportMessages.voiceBox(VoicePart.bass));
      await tester.tap(download);
      await tester.pump();

      h.engine.fail(VoicePart.bass, fatal: true);
      await settle(tester);
      // Held open while busy (AC12).
      expect(sheet, findsOneWidget);

      service.exportGate!.complete();
      await settle(tester);
      expect(sheet, findsNothing);
      expect(
        find.text(PlaybackMessages.errorHeading(PlaybackError.audio)),
        findsOneWidget,
      );
    });
  });
}

/// Thrown by the fake click writer; any error there is "couldn't be made".
class FileSystemExceptionStub implements Exception {
  const FileSystemExceptionStub();
}
