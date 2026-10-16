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

  Future<void> openExport(WidgetTester tester) async {
    await tester.tap(find.byTooltip(PlaybackMessages.download));
    await settle(tester);
    expect(sheet, findsOneWidget);
  }

  Future<void> tick(WidgetTester tester, String label) async {
    await tester.tap(box(label));
    await tester.pump();
  }

  bool downloadEnabled(WidgetTester tester) =>
      tester.widget<PrimaryPillButton>(download).onPressed != null;

  SemanticsData semanticsOf(WidgetTester tester, String label) =>
      tester.getSemantics(box(label)).getSemanticsData();
  // What TalkBack announces (AC21), not just how the box looks.
  bool isChecked(WidgetTester tester, String label) =>
      semanticsOf(tester, label).flagsCollection.isChecked ==
      CheckedState.isTrue;
  bool isEnabled(WidgetTester tester, String label) =>
      semanticsOf(tester, label).flagsCollection.isEnabled == Tristate.isTrue;

  group('selection (AC2-AC8)', () {
    testWidgets('opens empty with Download disabled', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      await openExport(tester);

      expect(find.text(ExportMessages.title), findsOneWidget);
      for (final voice in VoicePart.values) {
        expect(row(voice.name), findsOneWidget);
        expect(isChecked(tester, ExportMessages.voiceBox(voice)), isFalse);
      }
      expect(find.text(ExportMessages.allVoices), findsOneWidget);
      expect(find.text(ExportMessages.withClick), findsOneWidget);
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
    testWidgets('a ticked voice muted in the Mixer says so and still '
        'exports at gain 0 (Review Focus 1)', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester).setVoiceMuted(VoicePart.alto, muted: true);
      await openExport(tester);

      await tick(tester, ExportMessages.voiceBox(VoicePart.alto));
      expect(find.byKey(const ValueKey('export-muted-alto')), findsOneWidget);
      expect(downloadEnabled(tester), isTrue);
    });

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

    testWidgets('gains follow the Mixer: volume, mute, and solo leaving '
        'the others out', (tester) async {
      final service = FakeExportService();
      await pumpPlayback(tester, harness(service));
      controller(tester)
        ..setVoiceVolume(VoicePart.soprano, 0.5)
        ..setVoiceMuted(VoicePart.bass, muted: true);
      final all = ExportSelection.empty(playback(tester).available).toggleAll();

      Map<String, double> gains(ExportJob job) => {
        for (final input in job.inputs)
          input.track.pathSegments.last: input.gain,
      };
      expect(gains(buildExportJob(playback(tester), all, kTitle)), {
        'soprano.mp3': 0.5,
        'alto.mp3': 1.0,
        'tenor.mp3': 1.0,
        'bass.mp3': 0.0,
      });

      controller(tester).setVoiceSoloed(VoicePart.tenor, soloed: true);
      expect(gains(buildExportJob(playback(tester), all, kTitle)), {
        'soprano.mp3': 0.0,
        'alto.mp3': 0.0,
        'tenor.mp3': 1.0,
        'bass.mp3': 0.0,
      });
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
}

/// Thrown by the fake click writer; any error there is "couldn't be made".
class FileSystemExceptionStub implements Exception {
  const FileSystemExceptionStub();
}
