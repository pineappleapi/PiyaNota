import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_failure.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/retake/rephotograph.dart';
import 'package:piyanota_application/services/score_upload_api.dart';

/// PIYA-102 AC7/AC8 and PIYA-103 AC10 parsing behind PIYA-207 AC11/AC12.
void main() {
  group('failedVoiceCauses (PIYA-102 AC7, PIYA-103 AC10)', () {
    test('complete: causes per failed voice; unknown or missing is '
        'render_failed', () {
      final status = ProcessingStatus.fromJson({
        'status': 'complete',
        'percentComplete': 100,
        'scoreId': 5,
        'failedVoices': ['tenor', 'Bass', 'alto'],
        'failedVoiceCauses': {
          'tenor': 'unreadable',
          'bass': 'smudged_by_coffee',
          // Not a failed voice: ignored, never creates a failure.
          'soprano': 'unreadable',
        },
      });
      expect(status.failedVoices, {
        VoicePart.alto,
        VoicePart.tenor,
        VoicePart.bass,
      });
      expect(status.failedVoiceCauses, {
        VoicePart.tenor: VoiceFailureCause.unreadable,
        VoicePart.bass: VoiceFailureCause.renderFailed,
        VoicePart.alto: VoiceFailureCause.renderFailed,
      });
      expect(status.unreadableVoices, [VoicePart.tenor]);
      // AC11: N = 4 − len(failedVoices).
      expect(status.playableVoiceCount, 1);
    });

    test('only complete carries them (null otherwise)', () {
      final status = ProcessingStatus.fromJson({
        'status': 'transcribing',
        'percentComplete': 40,
        'failedVoices': ['tenor'],
        'failedVoiceCauses': {'tenor': 'unreadable'},
      });
      expect(status.failedVoices, isEmpty);
      expect(status.unreadableVoices, isEmpty);
      expect(status.playableVoiceCount, 4);
    });

    test('no failedVoiceCauses object: every failed voice is '
        'render_failed', () {
      final status = ProcessingStatus.fromJson({
        'status': 'complete',
        'failedVoices': ['tenor'],
        'failedVoiceCauses': null,
      });
      expect(status.failedVoiceCauses, {
        VoicePart.tenor: VoiceFailureCause.renderFailed,
      });
      expect(status.unreadableVoices, isEmpty);
    });

    test('PIYA-103 result: unreadable voices in SATB order', () {
      final result = ScoreResult.fromJson({
        'scoreId': 3,
        'jobId': 'job-3',
        'audioTracks': {
          'soprano': 'https://cdn.test/s.mp3',
          'alto': 'https://cdn.test/a.mp3',
        },
        'failedVoices': ['bass', 'tenor'],
        'failedVoiceCauses': {'bass': 'unreadable', 'tenor': 'render_failed'},
      });
      expect(result.unreadableVoices, [VoicePart.bass]);
      expect(
        result.failedVoiceCauses[VoicePart.tenor],
        VoiceFailureCause.renderFailed,
      );
    });
  });

  group('details (PIYA-102 AC8)', () {
    test('every field a retake pre-fills', () {
      final status = ProcessingStatus.fromJson({
        'status': 'failed',
        'failureReason': 'incomplete_voice_sequence',
        'title': ' Ave Maria ',
        'arranger': 'Bach',
        'tempoBpm': 72,
        'keySignature': 'Bb',
        'timeSignature': '3/4',
      });
      final details = status.details!;
      expect(details.title, 'Ave Maria');
      expect(details.arranger, 'Bach');
      expect(details.tempoBpm, 72);
      expect(details.keySignature, KeySignature.bFlat);
      expect(details.timeSignature, TimeSignature.threeFour);
    });

    test('optional fields missing or unknown stay "Not sure"', () {
      final details = ProcessingStatus.fromJson({
        'status': 'queued',
        'title': 'Ave',
        'tempoBpm': 999,
        'keySignature': 'H',
      }).details!;
      expect(details.arranger, '');
      expect(details.tempoBpm, isNull);
      expect(details.keySignature, isNull);
      expect(details.timeSignature, isNull);
    });

    test('no title: no details', () {
      expect(ProcessingStatus.fromJson({'status': 'queued'}).details, isNull);
    });
  });

  test('a whole-score retake sends replacesJobId (PIYA-101 AC12)', () {
    final fields = scoreFormFields(
      const ScoreDetails(title: 'Ave', tempoBpm: 80),
      replacesJobId: 'job-1',
    );
    expect(fields.first.key, 'replacesJobId');
    expect(fields.first.value, 'job-1');
    expect(
      scoreFormFields(const ScoreDetails(title: 'Ave')).map((f) => f.key),
      isNot(contains('replacesJobId')),
    );
  });

  group('AC11 wording', () {
    test('names the voices and counts N', () {
      expect(
        RephotographMessages.offerTitle([VoicePart.tenor]),
        'The Tenor part couldn\'t be read from these photos',
      );
      expect(
        RephotographMessages.offerTitle([VoicePart.tenor, VoicePart.bass]),
        'The Tenor and Bass parts couldn\'t be read from these photos',
      );
      expect(RephotographMessages.continueWith(3), 'Continue with 3 voices');
      expect(RephotographMessages.continueWith(1), 'Continue with 1 voice');
      expect(
        RephotographMessages.unreadableTitle(VoicePart.alto),
        'Alto couldn\'t be read from the photos',
      );
    });
  });
}
