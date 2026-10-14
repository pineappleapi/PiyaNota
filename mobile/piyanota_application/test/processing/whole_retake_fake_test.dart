import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/services/fake_processing_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/services/fake_score_upload_api.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/services/session_storage.dart';

import '../auth/auth_test_harness.dart';

const _account = 'singer@example.com';
const _step = FakeProcessingApi.defaultStepDuration;

/// Far enough for any fake job to reach its end.
const _end = 60;

class _Backend {
  _Backend() {
    final session = SessionStorage(
      FaultySecureStorage({'session_token': _account}),
    );
    String? lookup(String token) => token;
    library = FakeScoreLibraryApi(
      sessionStorage: session,
      accountForToken: lookup,
      latency: Duration.zero,
    );
    jobs = FakeProcessingApi(
      sessionStorage: session,
      accountForToken: lookup,
      library: library,
      latency: Duration.zero,
      clock: () => now,
    );
    upload = FakeScoreUploadApi(
      sessionStorage: session,
      accountForToken: lookup,
      library: library,
      jobs: jobs,
      latency: Duration.zero,
    );
  }

  late final FakeScoreLibraryApi library;
  late final FakeProcessingApi jobs;
  late final FakeScoreUploadApi upload;
  final DateTime start = DateTime(2026, 10, 14, 9);
  late DateTime now = start;

  Future<String> submit(String title, {String? replacesJobId}) async =>
      (await upload.submitImages(
        details: ScoreDetails(title: title, tempoBpm: 72),
        imagePaths: const ['p0.jpg', 'p1.jpg'],
        replacesJobId: replacesJobId,
      )).jobId;

  void at(int step) => now = start.add(_step * step);
}

Matcher _rejected(int status, String code) => throwsA(
  isA<UploadRejectedException>()
      .having((e) => e.statusCode, 'statusCode', status)
      .having((e) => e.code, 'code', code),
);

void main() {
  test('a title with "unreadable" completes with an unreadable Tenor and '
      'its details', () async {
    final b = _Backend();
    final jobId = await b.submit('Ave unreadable');
    b.at(_end);
    final status = await b.jobs.fetchStatus(jobId);
    expect(status.stage, ProcessingStage.complete);
    expect(status.unreadableVoices, [VoicePart.tenor]);
    expect(status.playableVoiceCount, 3);
    expect(status.details?.title, 'Ave unreadable');
    expect(status.details?.tempoBpm, 72);
  });

  test('completed with unreadable: the retake keeps the score id', () async {
    final b = _Backend();
    final jobId = await b.submit('Ave unreadable');
    b.at(_end);
    final scoreId = (await b.jobs.fetchStatus(jobId)).scoreId;
    final count = (await b.library.fetchLibrary()).length;

    final retakeId = await b.submit('Ave', replacesJobId: jobId);
    // Only one retake at a time.
    await expectLater(
      b.submit('Ave', replacesJobId: jobId),
      _rejected(409, retakeInProgressCode),
    );
    b.at(_end * 2);
    final retake = await b.jobs.fetchStatus(retakeId);
    expect(retake.stage, ProcessingStage.complete);
    expect(retake.scoreId, scoreId);
    expect((await b.library.fetchLibrary()).length, count);
    // Superseded once the retake completes.
    await expectLater(
      b.submit('Ave', replacesJobId: jobId),
      _rejected(409, notRetakeableCode),
    );
  });

  test('failed with incomplete_voice_sequence: the retake replaces the '
      'card', () async {
    final b = _Backend();
    final jobId = await b.submit('Ave missing voice');
    b.at(_end);
    final failed = await b.jobs.fetchStatus(jobId);
    expect(failed.stage, ProcessingStage.failed);
    expect(failed.failureReason, FailureReason.incompleteVoiceSequence);
    expect(failed.failedPageIndex, isNull);
    final oldScore = failed.scoreId;

    final retakeId = await b.submit('Ave', replacesJobId: jobId);
    b.at(_end * 2);
    final retake = await b.jobs.fetchStatus(retakeId);
    expect(retake.stage, ProcessingStage.complete);
    expect(retake.scoreId, isNot(oldScore));
    // Superseded at creation.
    await expectLater(
      b.submit('Ave', replacesJobId: jobId),
      _rejected(409, notRetakeableCode),
    );
  });

  test('a job that can\'t be retaken whole, or doesn\'t exist', () async {
    final b = _Backend();
    final ok = await b.submit('Ave');
    b.at(_end);
    await expectLater(
      b.submit('Ave', replacesJobId: ok),
      _rejected(409, notRetakeableCode),
    );
    await expectLater(
      b.submit('Ave', replacesJobId: 'fake-job-nope'),
      _rejected(404, jobNotFoundCode),
    );
  });

  test('render_failed only: not retakeable', () async {
    final b = _Backend();
    final jobId = FakeProcessingApi.demoJobId(
      FakeProcessingApi.renderFailedDemoScoreId,
    );
    expect(
      () => b.jobs.checkWholeRetake(account: _account, jobId: jobId),
      throwsA(isA<UploadRejectedException>()),
    );
  });
}
