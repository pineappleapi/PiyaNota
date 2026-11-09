import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_platform_interface.dart';
import 'package:shared_preferences_platform_interface/types.dart';
import 'package:piyanota_application/state/processing_providers.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/models/voice_failure.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/processing/processing_messages.dart';
import 'package:piyanota_application/screens/retake/rephotograph.dart';

import 'processing_fakes.dart';

const _details = ScoreDetails(title: kTitle, tempoBpm: 72);

ProcessingStatus _doneWith(
  Map<VoicePart, VoiceFailureCause> causes, {
  int scoreId = 7,
}) => ProcessingStatus(
  stage: ProcessingStage.complete,
  percentComplete: 100,
  scoreId: scoreId,
  failedVoices: causes.keys.toSet(),
  failedVoiceCauses: causes,
  details: _details,
);

/// Past the completion hold and the dialog's entrance.
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 500));
  }
}

Finder get _offer => find.byKey(const Key('rephotograph-offer'));

/// A preferences store whose first read waits for [gate], to hold
/// Processing inside its "answered yet?" check.
class _GatedPrefsStore extends InMemorySharedPreferencesStore {
  _GatedPrefsStore(this.gate) : super.empty();

  final Completer<void> gate;

  @override
  Future<Map<String, Object>> getAllWithParameters(
    GetAllParameters parameters,
  ) async {
    await gate.future;
    return super.getAllWithParameters(parameters);
  }
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('PIYA-207 AC11 after processing', () {
    testWidgets('an unreadable Tenor: offer first, N = 3', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          _doneWith({VoicePart.tenor: VoiceFailureCause.unreadable}),
        ]),
      );
      await pumpProcessing(tester, h);
      await _settle(tester);
      expect(_offer, findsOneWidget);
      expect(
        find.text(RephotographMessages.offerTitle([VoicePart.tenor])),
        findsOneWidget,
      );
      expect(find.text('Continue with 3 voices'), findsOneWidget);
      expect(find.text(RephotographMessages.rephotograph), findsOneWidget);
      // Routing waits for the choice (AC8).
      expect(find.textContaining('ROUTE:playback'), findsNothing);
    });

    testWidgets('N counts render_failed voices too', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          _doneWith({
            VoicePart.tenor: VoiceFailureCause.unreadable,
            VoicePart.bass: VoiceFailureCause.renderFailed,
          }),
        ]),
      );
      await pumpProcessing(tester, h);
      await _settle(tester);
      expect(find.text('Continue with 2 voices'), findsOneWidget);
    });

    testWidgets('no voice left (N = 0): no Continue', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          _doneWith({
            for (final voice in VoicePart.values)
              voice: VoiceFailureCause.unreadable,
          }),
        ]),
      );
      await pumpProcessing(tester, h);
      await _settle(tester);
      expect(_offer, findsOneWidget);
      expect(find.textContaining('Continue with'), findsNothing);
      expect(find.text(RephotographMessages.rephotograph), findsOneWidget);
    });

    testWidgets('a second complete while the first is being decided shows '
        'one offer', (tester) async {
      final gate = Completer<void>();
      SharedPreferencesStorePlatform.instance = _GatedPrefsStore(gate);
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          _doneWith({VoicePart.tenor: VoiceFailureCause.unreadable}),
        ]),
      );
      await pumpProcessing(tester, h);
      // The first complete is waiting on the preference read. Follow the
      // job afresh: its poll completes it a second time.
      final jobs = h.container.read(processingJobsProvider.notifier);
      jobs.forget(kJob);
      jobs.track(kJob, title: kTitle);
      await tester.pump();
      await tester.pump();
      gate.complete();
      await _settle(tester);
      expect(_offer, findsOneWidget);
    });

    testWidgets('render_failed only: straight to Playback', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          _doneWith({VoicePart.tenor: VoiceFailureCause.renderFailed}),
        ]),
      );
      await pumpProcessing(tester, h);
      await _settle(tester);
      expect(_offer, findsNothing);
      expect(find.text(playbackMarker(7)), findsOneWidget);
    });

    testWidgets('Continue: Playback, and never offered again for the job', (
      tester,
    ) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          _doneWith({VoicePart.tenor: VoiceFailureCause.unreadable}),
        ]),
      );
      await pumpProcessing(tester, h);
      await _settle(tester);
      await tester.tap(find.text('Continue with 3 voices'));
      await _settle(tester);
      expect(find.text(playbackMarker(7)), findsOneWidget);
      expect(await RephotographOfferPrefs.isAnswered(kJob), isTrue);
    });

    testWidgets('already answered for this jobId: straight to Playback', (
      tester,
    ) async {
      SharedPreferences.setMockInitialValues({
        RephotographOfferPrefs.keyFor(kJob): true,
      });
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          _doneWith({VoicePart.tenor: VoiceFailureCause.unreadable}),
        ]),
      );
      await pumpProcessing(tester, h);
      await _settle(tester);
      expect(_offer, findsNothing);
      expect(find.text(playbackMarker(7)), findsOneWidget);
    });

    testWidgets('system Back: library, no Playback, still unanswered', (
      tester,
    ) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          _doneWith({VoicePart.tenor: VoiceFailureCause.unreadable}),
        ]),
      );
      await pumpProcessing(tester, h);
      await _settle(tester);
      await tester.binding.handlePopRoute();
      await _settle(tester);
      expect(_offer, findsNothing);
      expect(find.text(kLibrary), findsOneWidget);
      expect(find.textContaining('ROUTE:playback'), findsNothing);
      expect(await RephotographOfferPrefs.isAnswered(kJob), isFalse);
    });

    testWidgets('Re-photograph: Capture for the whole score, pre-filled, '
        'replacing this job (AC12)', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          _doneWith({VoicePart.tenor: VoiceFailureCause.unreadable}),
        ]),
      );
      await pumpProcessing(tester, h);
      await _settle(tester);
      await tester.tap(find.text(RephotographMessages.rephotograph));
      await _settle(tester);
      expect(
        find.text('ROUTE:whole-retake $kJob $kTitle 72 7'),
        findsOneWidget,
      );
      expect(await RephotographOfferPrefs.isAnswered(kJob), isTrue);
    });
  });

  group('PIYA-207 AC7 failures', () {
    testWidgets('incomplete_voice_sequence: Re-photograph the whole score', (
      tester,
    ) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          ProcessingStatus(
            stage: ProcessingStage.failed,
            percentComplete: 30,
            failureReason: FailureReason.incompleteVoiceSequence,
            details: _details,
          ),
        ]),
      );
      await pumpProcessing(tester, h);
      expect(
        find.text(
          ProcessingMessages.failureBody(
            FailureReason.incompleteVoiceSequence,
            null,
          ),
        ),
        findsOneWidget,
      );
      expect(find.textContaining('Retake page'), findsNothing);
      await tester.tap(find.text(RephotographMessages.rephotograph));
      await _settle(tester);
      // A failed job's retake replaces its card: no score id carried.
      expect(
        find.text('ROUTE:whole-retake $kJob $kTitle 72 null'),
        findsOneWidget,
      );
    });

    testWidgets('synthesis_failed: retry-later copy, no retake', (
      tester,
    ) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([failed(FailureReason.synthesisFailed)]),
      );
      await pumpProcessing(tester, h);
      expect(find.text(RephotographMessages.rephotograph), findsNothing);
      expect(find.text(ProcessingMessages.backToLibrary), findsOneWidget);
    });
  });
}
