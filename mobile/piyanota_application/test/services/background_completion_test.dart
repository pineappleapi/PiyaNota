import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/models/local_submission.dart';
import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/services/background_completion.dart';
import 'package:piyanota_application/services/local_results_store.dart';
import 'package:piyanota_application/services/local_submission_store.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/services/score_result_api.dart';
import 'package:piyanota_application/services/submission_reconciler.dart';
import 'package:shared_preferences/shared_preferences.dart';

final _now = DateTime.utc(2026, 11, 10, 12);

class _Processing implements ProcessingApi {
  @override
  Future<ProcessingStatus> fetchStatus(String jobId) async =>
      throw const ProcessingServerException();

  @override
  Future<void> cancelJob(String jobId) async {}
}

class _JobList implements JobListApi {
  List<ListedJob> jobs = [];
  Object? error;

  @override
  Future<List<ListedJob>> listJobs() async {
    if (error != null) throw error!;
    return jobs;
  }
}

class _Results implements ScoreResultApi {
  @override
  Future<ScoreResult> fetchResult(int scoreId) async => ScoreResult.fromJson({
    'scoreId': scoreId,
    'audioTracks': {'soprano': 'https://good.example/audio/s.mp3'},
    'audioFiles': {
      'soprano': {
        'url': 'https://good.example/audio/s.mp3',
        'fileId': 'audio-s',
        'sizeBytes': 0,
      },
    },
  });

  @override
  Future<TimingFile> fetchTiming(Uri url) async => TimingFile.empty;
}

class _Downloader implements FileDownloader {
  @override
  Future<void> download(Uri url, String savePath) async =>
      File(savePath).writeAsString('bytes');
}

ListedJob _job(
  String jobId,
  String client,
  ProcessingStage stage, {
  int? scoreId,
}) => (
  jobId: jobId,
  clientSubmissionId: client,
  title: 'Ave',
  createdAt: _now.subtract(const Duration(minutes: 30)),
  status: ProcessingStatus(
    stage: stage,
    percentComplete: 40,
    scoreId: scoreId,
    failureReason: stage == ProcessingStage.failed
        ? FailureReason.unknown
        : null,
  ),
);

LocalSubmission _row(String id, String jobId) => LocalSubmission(
  clientSubmissionId: id,
  title: 'Ave',
  createdAt: _now.subtract(const Duration(minutes: 30)),
  jobId: jobId,
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory root;
  late _JobList list;
  late LocalSubmissionStore store;
  late BackgroundCompletion run;
  var foreground = false;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    root = await Directory.systemTemp.createTemp('bg_completion_test');
    list = _JobList();
    foreground = false;
    store = const LocalSubmissionStore();
    run = BackgroundCompletion(
      reconciler: SubmissionReconciler(
        processing: _Processing(),
        jobList: list,
        results: _Results(),
        submissions: store,
        resultsStore: LocalResultsStore(
          rootProvider: () async => root,
          downloader: _Downloader(),
        ),
        now: () => _now,
        isCancelled: () async => foreground,
      ),
      submissions: store,
      notified: const NotifiedJobsStore(),
      isCancelled: () async => foreground,
    );
  });

  tearDown(() async {
    if (root.existsSync()) await root.delete(recursive: true);
  });

  test('no converting row: nothing to do and the job stops', () async {
    await store.save([
      _row('c1', 'j1').copyWith(status: SubmissionStatus.ready),
    ]);
    final out = await run.run();
    expect(out.keepScheduled, isFalse);
    expect(out.notices, isEmpty);
  });

  test('finished job: row ready, one notice, job stops', () async {
    await store.save([_row('c1', 'j1')]);
    list.jobs = [_job('j1', 'c1', ProcessingStage.complete, scoreId: 9)];
    final out = await run.run();
    expect(out.notices, [(jobId: 'j1', title: 'Ave', ok: true)]);
    expect(out.keepScheduled, isFalse);
    final row = (await store.load()).single;
    expect(row.status, SubmissionStatus.ready);
    expect(row.scoreId, 9);
  });

  test('failed job: failed notice', () async {
    await store.save([_row('c1', 'j1')]);
    list.jobs = [_job('j1', 'c1', ProcessingStage.failed)];
    final out = await run.run();
    expect(out.notices.single.ok, isFalse);
  });

  test('still running: no notice, keeps scheduled', () async {
    await store.save([_row('c1', 'j1')]);
    list.jobs = [_job('j1', 'c1', ProcessingStage.transcribing)];
    final out = await run.run();
    expect(out.notices, isEmpty);
    expect(out.keepScheduled, isTrue);
  });

  test('already notified by the foreground: no second notice', () async {
    await store.save([_row('c1', 'j1')]);
    await const NotifiedJobsStore().add('j1');
    list.jobs = [_job('j1', 'c1', ProcessingStage.complete, scoreId: 9)];
    final out = await run.run();
    expect(out.notices, isEmpty);
    expect((await store.load()).single.status, SubmissionStatus.ready);
  });

  test('markNotified prevents a repeat on the next run', () async {
    await run.markNotified('j1');
    expect(await const NotifiedJobsStore().load(), {'j1'});
  });

  test('401: stops quietly, rows and notices untouched', () async {
    await store.save([_row('c1', 'j1')]);
    list.error = const ProcessingSessionExpiredException();
    final out = await run.run();
    expect(out.keepScheduled, isFalse);
    expect(out.notices, isEmpty);
    final row = (await store.load()).single;
    expect(row.status, SubmissionStatus.processing);
  });

  test('offline: keeps trying later, no notice', () async {
    await store.save([_row('c1', 'j1')]);
    list.error = const ProcessingNetworkException();
    final out = await run.run();
    expect(out.keepScheduled, isTrue);
    expect(out.notices, isEmpty);
  });

  test('already-failed rows are not announced again', () async {
    await store.save([
      _row(
        'c1',
        'j1',
      ).copyWith(status: SubmissionStatus.failed, failureCode: 'unknown'),
      _row('c2', 'j2'),
    ]);
    list.jobs = [_job('j2', 'c2', ProcessingStage.transcribing)];
    final out = await run.run();
    expect(out.notices, isEmpty);
  });

  test('scheduler: platform failures are swallowed', () async {
    const channel = MethodChannel('test/background');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          throw PlatformException(code: 'x');
        });
    addTearDown(
      () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null),
    );
    final scheduler = BackgroundCompletionScheduler(channel);
    await scheduler.schedule();
    await scheduler.cancel();
    await BackgroundCompletionScheduler().schedule(); // no native side
  });

  test('pickerOpen sends the flag on the background channel', () async {
    const channel = MethodChannel('test/background2');
    final calls = <MethodCall>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          calls.add(call);
          return null;
        });
    addTearDown(
      () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null),
    );
    final scheduler = BackgroundCompletionScheduler(channel);
    await scheduler.pickerOpen(true);
    await scheduler.pickerOpen(false);
    expect(calls.map((c) => c.method), ['pickerOpen', 'pickerOpen']);
    expect(calls.map((c) => (c.arguments as Map)['open']), [true, false]);
  });

  test('the app came to the foreground: no work, no notice, stays '
      'scheduled', () async {
    await store.save([_row('c1', 'j1')]);
    list.jobs = [_job('j1', 'c1', ProcessingStage.complete, scoreId: 9)];
    foreground = true;
    final out = await run.run();
    expect(out.keepScheduled, isTrue);
    expect(out.notices, isEmpty);
    expect((await store.load()).single.status, SubmissionStatus.processing);
  });
}
