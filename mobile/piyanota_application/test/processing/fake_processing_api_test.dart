import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/services/fake_processing_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/services/fake_score_upload_api.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/services/session_storage.dart';

import '../auth/auth_test_harness.dart';

const _ok = 'singer@example.com';
const _flaky = 'singer${FakeScoreLibraryApi.flakyDomain}';
const _step = FakeProcessingApi.defaultStepDuration;

/// The fake upload, library and jobs wired together as the providers do,
/// on a clock the test moves.
class _Backend {
  _Backend(String? account) {
    storage = FaultySecureStorage({'session_token': ?account});
    final session = SessionStorage(storage);
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

  late final FaultySecureStorage storage;
  late final FakeScoreLibraryApi library;
  late final FakeProcessingApi jobs;
  late final FakeScoreUploadApi upload;
  DateTime now = DateTime(2026, 10, 8, 9);

  Future<String> submit([int pages = 3]) async => (await upload.submitImages(
    details: const ScoreDetails(title: 'Ave'),
    imagePaths: [for (var i = 0; i < pages; i++) 'p$i.jpg'],
  )).jobId;

  /// The flaky account's submit itself fails three times in four; this
  /// gets past those to the next registered job.
  Future<String> submitPastUploadErrors() async {
    while (true) {
      try {
        return await submit();
      } on ScoreUploadException {
        continue;
      }
    }
  }

  void at(int step) => now = DateTime(2026, 10, 8, 9).add(_step * step);
}

void main() {
  test('a job walks every stage to complete with page and ETA', () async {
    final b = _Backend(_ok);
    final jobId = await b.submit();
    final seen = <ProcessingStage>[];
    for (var step = 0; step <= 12; step++) {
      b.at(step);
      final s = await b.jobs.fetchStatus(jobId);
      seen.add(s.stage);
      if (step < 2) expect(s.estimatedRemainingSeconds, isNull);
      if (step == 4) {
        expect((s.currentPage, s.totalPages), (2, 3));
        expect(s.stage, ProcessingStage.preprocessing);
      }
    }
    expect(seen.first, ProcessingStage.queued);
    expect(seen.last, ProcessingStage.complete);
    expect(seen, contains(ProcessingStage.detectingStaff));
    expect(seen, contains(ProcessingStage.synthesizing));
    final last = await b.jobs.fetchStatus(jobId);
    expect(last.percentComplete, 100);
    expect((last.currentPage, last.totalPages), (3, 3));
    expect(last.scoreId, isNotNull);
  });

  test('flaky accounts cycle no-staff, unsupported, blip, success', () async {
    final b = _Backend(_flaky);
    final noStaff = await b.submitPastUploadErrors();
    final unsupported = await b.submitPastUploadErrors();
    final blip = await b.submitPastUploadErrors();
    final success = await b.submitPastUploadErrors();

    b.at(20);
    final a = await b.jobs.fetchStatus(noStaff);
    expect(a.stage, ProcessingStage.failed);
    expect(a.failureReason, FailureReason.noStaffDetected);
    expect(a.failedPageIndex, 1);

    final c = await b.jobs.fetchStatus(unsupported);
    expect(c.failureReason, FailureReason.unsupportedStaffLayout);
    expect(c.failedPageIndex, 0);

    expect((await b.jobs.fetchStatus(blip)).stage, ProcessingStage.complete);
    expect((await b.jobs.fetchStatus(success)).stage, ProcessingStage.complete);

    b.at(4);
    await expectLater(
      b.jobs.fetchStatus(blip),
      throwsA(isA<ProcessingNetworkException>()),
    );
  });

  test('jobs are private to their account; no token is a 401', () async {
    final b = _Backend(_ok);
    final jobId = await b.submit();
    b.storage.values['session_token'] = 'someone@else.test';
    await expectLater(
      b.jobs.fetchStatus(jobId),
      throwsA(isA<ProcessingJobNotFoundException>()),
    );
    b.storage.values.remove('session_token');
    await expectLater(
      b.jobs.fetchStatus(jobId),
      throwsA(isA<ProcessingSessionExpiredException>()),
    );
  });

  test(
    'cancel removes the placeholder score; after the end it is 409',
    () async {
      final b = _Backend(_ok);
      final before = (await b.library.fetchLibrary()).length;
      final jobId = await b.submit();
      expect((await b.library.fetchLibrary()).length, before + 1);
      await b.jobs.cancelJob(jobId);
      expect((await b.library.fetchLibrary()).length, before);
      expect(
        (await b.jobs.fetchStatus(jobId)).stage,
        ProcessingStage.cancelled,
      );
      await expectLater(
        b.jobs.cancelJob(jobId),
        throwsA(isA<ProcessingConflictException>()),
      );

      final finished = await b.submit();
      b.at(12);
      await expectLater(
        b.jobs.cancelJob(finished),
        throwsA(isA<ProcessingConflictException>()),
      );
    },
  );

  test('resubmitting the failed page starts a job that succeeds', () async {
    final b = _Backend(_flaky);
    final noStaff = await b.submitPastUploadErrors();
    b.at(5);
    await expectLater(
      b.upload.resubmitPage(jobId: noStaff, pageIndex: 0, imagePath: 'x.jpg'),
      throwsA(
        isA<UploadRejectedException>().having(
          (e) => e.code,
          'code',
          pageNotRetakeableCode,
        ),
      ),
      reason: 'only the page that failed can be replaced',
    );
    final retake = await b.upload.resubmitPage(
      jobId: noStaff,
      pageIndex: 1,
      imagePath: 'x.jpg',
    );
    expect(retake.originalJobId, noStaff);
    b.at(5 + 12);
    final s = await b.jobs.fetchStatus(retake.replacementJobId);
    expect(s.stage, ProcessingStage.complete);
    expect(s.scoreId, isNotNull);

    final unsupported = await b.submitPastUploadErrors();
    b.at(5 + 12 + 5);
    await expectLater(
      b.upload.resubmitPage(
        jobId: unsupported,
        pageIndex: 0,
        imagePath: 'x.jpg',
      ),
      throwsA(isA<UploadRejectedException>()),
      reason: 'a layout problem cannot be fixed by retaking',
    );
    await expectLater(
      b.upload.resubmitPage(jobId: 'nope', pageIndex: 0, imagePath: 'x.jpg'),
      throwsA(
        isA<UploadRejectedException>().having(
          (e) => e.code,
          'code',
          jobNotFoundCode,
        ),
      ),
    );
  });
}
