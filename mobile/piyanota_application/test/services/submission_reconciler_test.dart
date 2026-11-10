import 'dart:async';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/models/local_submission.dart';
import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/services/local_results_store.dart';
import 'package:piyanota_application/services/local_submission_store.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/services/score_result_api.dart';
import 'package:piyanota_application/services/submission_reconciler.dart';
import 'package:piyanota_application/state/local_submission_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart'
    show CancelOutcome;
import 'package:shared_preferences/shared_preferences.dart';

final _now = DateTime.utc(2026, 11, 10, 12);

class _Processing implements ProcessingApi {
  /// jobId -> ProcessingStatus or a ProcessingException to throw.
  final Map<String, Object> answers = {};
  final List<String> asked = [];

  @override
  Future<ProcessingStatus> fetchStatus(String jobId) async {
    asked.add(jobId);
    final a = answers[jobId];
    if (a is ProcessingException) throw a;
    return (a as ProcessingStatus?) ??
        (throw const ProcessingServerException());
  }

  @override
  Future<void> cancelJob(String jobId) async {}
}

class _JobList implements JobListApi {
  List<ListedJob> jobs = [];
  Object? error;
  int calls = 0;
  Completer<void>? gate;

  @override
  Future<List<ListedJob>> listJobs() async {
    calls++;
    await gate?.future;
    if (error != null) throw error!;
    return jobs;
  }
}

class _Results implements ScoreResultApi {
  Object? error;
  String? version;
  int fetches = 0;

  @override
  Future<ScoreResult> fetchResult(int scoreId) async {
    fetches++;
    if (error != null) throw error!;
    return ScoreResult.fromJson({
      'scoreId': scoreId,
      'version': ?version,
      'audioTracks': {'soprano': 'https://good.example/audio/s.mp3'},
      'audioFiles': {
        'soprano': {
          'url': 'https://good.example/audio/s.mp3',
          'fileId': 'audio-s${version ?? ''}',
          'sizeBytes': 0,
        },
      },
    });
  }

  @override
  Future<TimingFile> fetchTiming(Uri url) async => TimingFile.empty;
}

class _Downloader implements FileDownloader {
  final List<Uri> calls = [];
  bool fail = false;

  @override
  Future<void> download(Uri url, String savePath) async {
    calls.add(url);
    if (fail) throw const ExpiredUrlException();
    await File(savePath).writeAsString('bytes');
  }
}

ListedJob _job(
  String jobId, {
  String? client,
  ProcessingStage stage = ProcessingStage.transcribing,
  int? percent = 40,
  int? scoreId,
  FailureReason? reason,
  String? title = 'Ave',
}) => (
  jobId: jobId,
  clientSubmissionId: client,
  title: title,
  createdAt: _now.subtract(const Duration(minutes: 30)),
  status: ProcessingStatus(
    stage: stage,
    percentComplete: percent,
    scoreId: scoreId,
    failureReason: reason,
  ),
);

LocalSubmission _row(
  String id, {
  String? jobId,
  SubmissionStatus status = SubmissionStatus.processing,
  String? failureCode,
  String? replacesJobId,
  Duration age = const Duration(minutes: 30),
}) => LocalSubmission(
  clientSubmissionId: id,
  title: 'Ave',
  createdAt: _now.subtract(age),
  jobId: jobId,
  status: status,
  failureCode: failureCode,
  replacesJobId: replacesJobId,
);

void main() {
  late Directory root;
  late _Processing processing;
  late _JobList list;
  late _Results results;
  late _Downloader downloader;
  late LocalSubmissionStore store;
  late LocalResultsStore resultsStore;
  late SubmissionReconciler reconciler;
  var cancelled = <bool>[];

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    root = await Directory.systemTemp.createTemp('reconcile_test');
    processing = _Processing();
    list = _JobList();
    results = _Results();
    downloader = _Downloader();
    store = const LocalSubmissionStore();
    cancelled = [];
    resultsStore = LocalResultsStore(
      rootProvider: () async => root,
      downloader: downloader,
    );
    reconciler = SubmissionReconciler(
      processing: processing,
      jobList: list,
      results: results,
      submissions: store,
      resultsStore: resultsStore,
      now: () => _now,
      minInterval: Duration.zero,
      // Scripted: each call takes the next answer, then false.
      isCancelled: () async =>
          cancelled.isEmpty ? false : cancelled.removeAt(0),
    );
  });

  tearDown(() async {
    if (root.existsSync()) await root.delete(recursive: true);
  });

  Future<Map<String, LocalSubmission>> rows() async => {
    for (final r in await store.load()) r.clientSubmissionId: r,
  };

  test('a failed row superseded by a replacement with a job is dropped '
      '(crash between the 202 and replaceFailedJob)', () async {
    await store.save([
      _row(
        'old',
        jobId: 'j-old',
        status: SubmissionStatus.failed,
        failureCode: 'no_staff_detected',
      ),
      _row('new', jobId: 'j-new', replacesJobId: 'j-old'),
    ]);
    list.jobs = [_job('j-new', client: 'new')];
    await reconciler.run();
    expect((await rows()).keys, ['new']);
  });

  test('a failed row whose replacement never got a job is kept', () async {
    await store.save([
      _row(
        'old',
        jobId: 'j-old',
        status: SubmissionStatus.failed,
        failureCode: 'no_staff_detected',
      ),
      _row(
        'new',
        status: SubmissionStatus.failed,
        failureCode: 'queue_full',
        replacesJobId: 'j-old',
      ),
    ]);
    await reconciler.run();
    expect((await rows()).keys.toSet(), {'old', 'new'});
  });

  test('a failed network row WITH a job is revived from the server (kept '
      'retry behaviour)', () async {
    await store.save([
      _row(
        'c1',
        jobId: 'j1',
        status: SubmissionStatus.failed,
        failureCode: 'network',
      ),
    ]);
    list.jobs = [_job('j1', client: 'c1')];
    await reconciler.run();
    expect((await rows())['c1']!.status, SubmissionStatus.processing);
  });

  test('complete: downloads the result, then marks the row ready', () async {
    await store.save([_row('c1', jobId: 'j1')]);
    list.jobs = [
      _job('j1', client: 'c1', stage: ProcessingStage.complete, scoreId: 9),
    ];
    expect(await reconciler.run(), ReconcileResult.done);
    final row = (await rows())['c1']!;
    expect(row.status, SubmissionStatus.ready);
    expect(row.scoreId, 9);
    expect(downloader.calls, isNotEmpty);
    expect(
      Directory('${root.path}${Platform.pathSeparator}9').existsSync(),
      isTrue,
    );
  });

  test('complete but the result call fails offline: stays processing, '
      'retried next run', () async {
    await store.save([_row('c1', jobId: 'j1')]);
    list.jobs = [
      _job('j1', client: 'c1', stage: ProcessingStage.complete, scoreId: 9),
    ];
    results.error = const ScoreResultNetworkException();
    await reconciler.run();
    expect((await rows())['c1']!.status, SubmissionStatus.processing);
    results.error = null;
    await reconciler.run();
    expect((await rows())['c1']!.status, SubmissionStatus.ready);
  });

  test('failed: row failed with the server reason as its code', () async {
    await store.save([_row('c1', jobId: 'j1')]);
    list.jobs = [
      _job(
        'j1',
        client: 'c1',
        stage: ProcessingStage.failed,
        reason: FailureReason.noStaffDetected,
      ),
    ];
    await reconciler.run();
    final row = (await rows())['c1']!;
    expect(row.status, SubmissionStatus.failed);
    expect(row.failureCode, 'no_staff_detected');
  });

  test('running: progress is saved on the row', () async {
    await store.save([_row('c1', jobId: 'j1')]);
    list.jobs = [_job('j1', client: 'c1', percent: 63)];
    await reconciler.run();
    expect((await rows())['c1']!.percentComplete, 63);
  });

  test('job missing from the list and 404 on status: row dropped', () async {
    await store.save([_row('c1', jobId: 'j1'), _row('c2', jobId: 'j2')]);
    list.jobs = [_job('j2', client: 'c2')];
    processing.answers['j1'] = const ProcessingJobNotFoundException();
    await reconciler.run();
    expect((await rows()).keys, ['c2']);
    expect(processing.asked, ['j1']); // only the missing one is asked
  });

  test('cancelled on the server: row dropped', () async {
    await store.save([_row('c1', jobId: 'j1')]);
    list.jobs = [_job('j1', client: 'c1', stage: ProcessingStage.cancelled)];
    await reconciler.run();
    expect(await rows(), isEmpty);
  });

  test('adopts a running server job the phone lacks; finished ones are '
      'not adopted', () async {
    list.jobs = [
      _job('j1', client: 'c-server', percent: 20),
      _job('j2'), // sent without a clientSubmissionId
      _job('j3', stage: ProcessingStage.complete, scoreId: 4),
      _job('j4', stage: ProcessingStage.failed),
    ];
    await reconciler.run();
    final r = await rows();
    expect(r.keys.toSet(), {'c-server', 'job-j2'});
    expect(r['c-server']!.jobId, 'j1');
    expect(r['c-server']!.percentComplete, 20);
    expect(r['c-server']!.status, SubmissionStatus.processing);
    // Running again does not duplicate.
    await reconciler.run();
    expect((await store.load()).length, 2);
  });

  test('pre-202 row inside the grace window is left alone', () async {
    await store.save([_row('c1', age: const Duration(minutes: 1))]);
    await reconciler.run();
    expect((await rows())['c1']!.status, SubmissionStatus.processing);
  });

  test(
    'pre-202 row past the grace window: server has it -> adopt jobId',
    () async {
      await store.save([_row('c1')]);
      list.jobs = [_job('j1', client: 'c1', percent: 10)];
      await reconciler.run();
      final row = (await rows())['c1']!;
      expect(row.jobId, 'j1');
      expect(row.status, SubmissionStatus.processing);
    },
  );

  test(
    'pre-202 row past the grace window: server lacks it -> interrupted',
    () async {
      await store.save([_row('c1')]);
      await reconciler.run();
      final row = (await rows())['c1']!;
      expect(row.status, SubmissionStatus.failed);
      expect(row.failureCode, SubmissionFailure.interrupted);
    },
  );

  test('a row failed as network/unknown is revived when the server has the '
      'job; a refusal stays failed', () async {
    await store.save([
      _row('c1', status: SubmissionStatus.failed, failureCode: 'network'),
      _row('c2', status: SubmissionStatus.failed, failureCode: 'queue_full'),
    ]);
    list.jobs = [_job('j1', client: 'c1'), _job('j2', client: 'c2')];
    await reconciler.run();
    final r = await rows();
    expect(r['c1']!.status, SubmissionStatus.processing);
    expect(r['c1']!.jobId, 'j1');
    expect(r['c2']!.status, SubmissionStatus.failed);
  });

  test('a dismissed row is not resurrected from the server list', () async {
    await store.markDismissed(
      ['c1'],
      _now,
      retention: SubmissionReconciler.retention,
    );
    await store.markDismissed(
      ['j2'],
      _now,
      retention: SubmissionReconciler.retention,
    );
    list.jobs = [_job('j1', client: 'c1'), _job('j2')];
    await reconciler.run();
    expect(await rows(), isEmpty);
  });

  test('cancel before the 202, then the upload lands: the tombstone hides '
      'the job the server created', () async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final ctl = container.read(localSubmissionsProvider.notifier);
    await ctl.begin(clientSubmissionId: 'c1', title: 'Ave');
    expect(await ctl.cancel('c1'), CancelOutcome.cancelled);
    expect(await store.load(fresh: true), isEmpty);

    // The request was already on the wire: the server made the job.
    list.jobs = [_job('j1', client: 'c1', percent: 10)];
    await reconciler.run();
    expect(await rows(), isEmpty);
    expect(processing.asked, isEmpty);
  });

  test('a dismissed id older than the retention window is forgotten', () async {
    await store.markDismissed(
      ['old'],
      _now.subtract(SubmissionReconciler.retention * 2),
      retention: SubmissionReconciler.retention,
    );
    await store.markDismissed(
      ['new'],
      _now,
      retention: SubmissionReconciler.retention,
    );
    expect((await store.loadDismissed()).keys, ['new']);
  });

  test('single-flight: overlapping runs share one list call', () async {
    list.gate = Completer<void>();
    final a = reconciler.run();
    final b = reconciler.run();
    list.gate!.complete();
    expect(await a, ReconcileResult.done);
    expect(await b, ReconcileResult.done);
    expect(list.calls, 1);
  });

  test('runs closer than minInterval are skipped unless forced', () async {
    final spaced = SubmissionReconciler(
      processing: processing,
      jobList: list,
      results: results,
      submissions: store,
      resultsStore: LocalResultsStore(
        rootProvider: () async => root,
        downloader: downloader,
      ),
      now: () => _now,
    );
    expect(await spaced.run(), ReconcileResult.done);
    expect(await spaced.run(), ReconcileResult.skipped);
    expect(await spaced.run(force: true), ReconcileResult.done);
    expect(list.calls, 2);
  });

  test('401 on the list: stops quietly, rows untouched', () async {
    await store.save([_row('c1', jobId: 'j1')]);
    list.error = const ProcessingSessionExpiredException();
    expect(await reconciler.run(), ReconcileResult.sessionExpired);
    expect((await rows())['c1']!.status, SubmissionStatus.processing);
  });

  test('401 mid-run (status or result): stops, nothing cleared', () async {
    await store.save([_row('c1', jobId: 'j1'), _row('c2', jobId: 'j2')]);
    processing.answers['j1'] = const ProcessingSessionExpiredException();
    expect(await reconciler.run(), ReconcileResult.sessionExpired);
    expect((await rows()).keys.toSet(), {'c1', 'c2'});

    list.jobs = [
      _job('j2', client: 'c2', stage: ProcessingStage.complete, scoreId: 3),
    ];
    results.error = const ScoreResultSessionExpiredException();
    expect(await reconciler.run(), ReconcileResult.sessionExpired);
    expect((await rows())['c2']!.status, SubmissionStatus.processing);
  });

  test('offline list: unavailable, rows untouched', () async {
    await store.save([_row('c1', jobId: 'j1')]);
    list.error = const ProcessingNetworkException();
    expect(await reconciler.run(), ReconcileResult.unavailable);
    expect((await rows())['c1']!.jobId, 'j1');
  });

  test('429 honours retryAfter: no run, not even forced, until it is over; '
      'a 429 without it waits the default', () async {
    var clock = _now;
    final timed = SubmissionReconciler(
      processing: processing,
      jobList: list,
      results: results,
      submissions: store,
      resultsStore: LocalResultsStore(
        rootProvider: () async => root,
        downloader: downloader,
      ),
      now: () => clock,
      minInterval: Duration.zero,
    );
    await store.save([_row('c1', jobId: 'j1')]);
    list.error = const ProcessingRateLimitedException(
      retryAfter: Duration(seconds: 45),
    );
    expect(await timed.run(), ReconcileResult.rateLimited);
    expect(list.calls, 1);

    clock = _now.add(const Duration(seconds: 44));
    expect(await timed.run(), ReconcileResult.skipped);
    expect(await timed.run(force: true), ReconcileResult.skipped);
    expect(list.calls, 1, reason: 'no request while the server said wait');

    clock = _now.add(const Duration(seconds: 46));
    list.error = const ProcessingRateLimitedException();
    expect(await timed.run(), ReconcileResult.rateLimited);
    expect(list.calls, 2);
    clock = clock.add(
      SubmissionReconciler.defaultRateLimitWait - const Duration(seconds: 1),
    );
    expect(await timed.run(), ReconcileResult.skipped);
    clock = clock.add(const Duration(seconds: 2));
    list.error = null;
    expect(await timed.run(), ReconcileResult.done);
    expect((await rows())['c1']!.jobId, 'j1');
  });

  test(
    '429 on a single status read keeps what is settled and backs off',
    () async {
      await store.save([_row('c1', jobId: 'j1'), _row('c2', jobId: 'j2')]);
      list.jobs = [_job('j1', client: 'c1', percent: 70)];
      processing.answers['j2'] = const ProcessingRateLimitedException(
        retryAfter: Duration(seconds: 30),
      );
      expect(await reconciler.run(), ReconcileResult.rateLimited);
      expect((await rows())['c1']!.percentComplete, 70);
      expect(await reconciler.run(), ReconcileResult.skipped);
    },
  );

  test('ready rows older than the retention window are pruned', () async {
    await store.save([
      _row(
        'old',
        jobId: 'j1',
        status: SubmissionStatus.ready,
        age: SubmissionReconciler.retention + const Duration(days: 1),
      ),
      _row('fresh', jobId: 'j2', status: SubmissionStatus.ready),
    ]);
    await reconciler.run();
    expect((await rows()).keys, ['fresh']);
  });

  test('parseJobList skips unusable items and reads the rest', () {
    final jobs = HttpProcessingApi.parseJobList({
      'data': {
        'jobs': [
          {
            'jobId': 'j1',
            'status': 'running_unknown_stage',
            'clientSubmissionId': 'c1',
            'createdAt': '2026-11-10T08:00:00Z',
          },
          {'jobId': 'j2'},
          'junk',
        ],
      },
    });
    expect(jobs.length, 1);
    expect(jobs.single.clientSubmissionId, 'c1');
    expect(jobs.single.status.stage, ProcessingStage.unknown);
    expect(
      () => HttpProcessingApi.parseJobList({'data': {}}),
      throwsA(isA<ProcessingServerException>()),
    );
  });

  test('cancel check between rows: stops, keeps what was settled, adopts '
      'nothing', () async {
    await store.save([_row('a', jobId: 'j-a'), _row('b', jobId: 'j-b')]);
    list.jobs = [
      _job(
        'j-a',
        client: 'a',
        stage: ProcessingStage.failed,
        reason: FailureReason.noStaffDetected,
      ),
      _job(
        'j-b',
        client: 'b',
        stage: ProcessingStage.failed,
        reason: FailureReason.noStaffDetected,
      ),
      _job('j-c', client: 'c'),
    ];
    cancelled = [false, true]; // before row a, before row b
    expect(await reconciler.run(), ReconcileResult.cancelled);
    final saved = await rows();
    expect(saved['a']!.status, SubmissionStatus.failed);
    expect(saved['b']!.status, SubmissionStatus.processing);
    expect(saved.keys, isNot(contains('c')), reason: 'no adoption');
  });

  test('a new version whose download failed resets the throttle so the next '
      'open revalidates at once; the saved copy stays', () async {
    results.version = 'v1';
    await resultsStore.sync(
      9,
      (await results.fetchResult(9)).rawJson!,
      refetch: () async => null,
    );
    await resultsStore.markChecked(9, _now);
    expect(await resultsStore.lastChecked(9), isNotNull);

    results.version = 'v2';
    downloader.fail = true;
    await store.save([_row('a', jobId: 'j-a')]);
    list.jobs = [
      _job('j-a', client: 'a', stage: ProcessingStage.complete, scoreId: 9),
    ];
    await reconciler.run();
    expect(await resultsStore.storedVersion(9), 'v1');
    expect(await resultsStore.lastChecked(9), isNull);
  });

  test('a new version that downloaded keeps the throttle', () async {
    results.version = 'v1';
    await resultsStore.sync(
      9,
      (await results.fetchResult(9)).rawJson!,
      refetch: () async => null,
    );
    await resultsStore.markChecked(9, _now);

    results.version = 'v2';
    await store.save([_row('a', jobId: 'j-a')]);
    list.jobs = [
      _job('j-a', client: 'a', stage: ProcessingStage.complete, scoreId: 9),
    ];
    await reconciler.run();
    expect(await resultsStore.storedVersion(9), 'v2');
    expect(await resultsStore.lastChecked(9), isNotNull);
  });
}
