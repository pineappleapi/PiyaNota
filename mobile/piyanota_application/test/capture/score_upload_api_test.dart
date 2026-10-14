import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/config/api_config.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/services/fake_score_upload_api.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/services/session_storage.dart';

import '../auth/auth_test_harness.dart';

/// Answers every request with one canned response (or a connection error)
/// and keeps the request so path, headers and parts can be checked.
class _StubAdapter implements HttpClientAdapter {
  _StubAdapter({
    this.status = 202,
    this.body = _accepted,
    this.headers = const {},
    this.connectionFails = false,
    this.rawBody,
    this.holdUntilCancelled = false,
  });

  /// Never answers; fails only once the request is cancelled.
  final bool holdUntilCancelled;

  final int status;
  final Object? body;
  final String? rawBody;
  final Map<String, List<String>> headers;
  final bool connectionFails;
  RequestOptions? lastRequest;
  int requests = 0;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests++;
    lastRequest = options;
    await requestStream?.drain<void>();
    if (holdUntilCancelled) {
      await cancelFuture;
      throw DioException.requestCancelled(
        requestOptions: options,
        reason: 'cancelled',
      );
    }
    if (connectionFails) {
      throw DioException.connectionError(
        requestOptions: options,
        reason: 'Simulated offline',
      );
    }
    return ResponseBody.fromString(
      rawBody ?? jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [
          rawBody == null ? Headers.jsonContentType : 'text/html',
        ],
        ...headers,
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

const _token = 'sess_a1b2c3d4';
const _accepted = {
  'data': {'jobId': 'job-7', 'status': 'queued', 'pageCount': 2},
  'success': true,
  'status': 202,
};

HttpScoreUploadApi _apiWith(_StubAdapter adapter, {String? token = _token}) {
  final dio = Dio(BaseOptions(baseUrl: 'https://api.test'))
    ..httpClientAdapter = adapter;
  return HttpScoreUploadApi(
    dio,
    SessionStorage(FaultySecureStorage({'session_token': ?token})),
  );
}

void main() {
  late Directory temp;
  late String page1;
  late String page2;
  late String pdf;

  setUpAll(() {
    temp = Directory.systemTemp.createTempSync('piya206_upload');
    page1 = '${temp.path}/a.jpg';
    page2 = '${temp.path}/b.jpg';
    pdf = '${temp.path}/score.pdf';
    File(page1).writeAsBytesSync([0xFF, 0xD8, 1]);
    File(page2).writeAsBytesSync([0xFF, 0xD8, 2]);
    File(pdf).writeAsStringSync('%PDF-1.7');
  });
  tearDownAll(() => temp.deleteSync(recursive: true));

  group('scoreFormFields (PIYA-101 AC8)', () {
    test('title only: optional fields are left out, not sent empty', () {
      final fields = scoreFormFields(const ScoreDetails(title: '  Ave  '));
      expect(fields.map((e) => '${e.key}=${e.value}'), ['title=Ave']);
    });

    test('every answer uses the exact API spelling', () {
      final fields = Map.fromEntries(
        scoreFormFields(
          const ScoreDetails(
            title: 'Pasko Na Naman',
            arranger: ' F. Santiago ',
            keySignature: KeySignature.bFlat,
            timeSignature: TimeSignature.sixEight,
            tempoBpm: 96,
          ),
        ),
      );
      expect(fields, {
        'title': 'Pasko Na Naman',
        'arranger': 'F. Santiago',
        'tempoBpm': '96',
        'keySignature': 'Bb',
        'timeSignature': '6/8',
      });
    });

    test('"Other" time and blank arranger are omitted', () {
      final keys = scoreFormFields(
        const ScoreDetails(
          title: 'X',
          arranger: '   ',
          timeSignature: TimeSignature.other,
        ),
      ).map((e) => e.key);
      expect(keys, ['title']);
    });

    test('sharp keys use ASCII #', () {
      expect(KeySignature.fSharp.apiValue, 'F#');
      expect(KeySignature.cFlat.apiValue, 'Cb');
    });
  });

  group('HttpScoreUploadApi', () {
    test('images go to PIYA-101 as ordered "pages" JPEG parts', () async {
      final adapter = _StubAdapter();
      final job = await _apiWith(adapter).submitImages(
        details: const ScoreDetails(title: 'Ave', tempoBpm: 80),
        imagePaths: [page2, page1],
      );
      expect(job.jobId, 'job-7');
      expect(job.pageCount, 2);
      final request = adapter.lastRequest!;
      expect(request.path, ApiConfig.submitImagesPath);
      expect(request.method, 'POST');
      expect(request.headers['Authorization'], 'Bearer $_token');
      final form = request.data as FormData;
      expect(form.fields.map((e) => e.key), ['title', 'tempoBpm']);
      expect(form.files.map((e) => e.key), ['pages', 'pages']);
      expect(form.files.map((e) => e.value.filename), [
        'page-1.jpg',
        'page-2.jpg',
      ]);
      expect(form.files.first.value.contentType.toString(), 'image/jpeg');
    });

    test(
      'a PDF goes to PIYA-310 as one "file" part with a long timeout',
      () async {
        final adapter = _StubAdapter();
        await _apiWith(adapter).submitPdf(
          details: const ScoreDetails(title: 'Ave'),
          pdfPath: pdf,
        );
        final request = adapter.lastRequest!;
        expect(request.path, ApiConfig.submitPdfPath);
        expect(request.receiveTimeout, ApiConfig.pdfReceiveTimeout);
        final form = request.data as FormData;
        expect(form.files.single.key, 'file');
        expect(
          form.files.single.value.contentType.toString(),
          'application/pdf',
        );
      },
    );

    test('no stored token fails before any request', () async {
      final adapter = _StubAdapter();
      await expectLater(
        _apiWith(adapter, token: null).submitImages(
          details: const ScoreDetails(title: 'Ave'),
          imagePaths: [page1],
        ),
        throwsA(isA<UploadSessionExpiredException>()),
      );
      expect(adapter.requests, 0);
    });

    test('offline is a network failure', () async {
      await expectLater(
        _apiWith(_StubAdapter(connectionFails: true)).submitImages(
          details: const ScoreDetails(title: 'Ave'),
          imagePaths: [page1],
        ),
        throwsA(isA<UploadNetworkException>()),
      );
    });

    test('a bare 404 on a whole-score retake is job_not_found; without '
        'replacesJobId it stays bare', () async {
      Future<void> check(String? replaces, Matcher code) => expectLater(
        _apiWith(_StubAdapter(status: 404, body: {})).submitImages(
          details: const ScoreDetails(title: 'Ave'),
          imagePaths: [page1],
          replacesJobId: replaces,
        ),
        throwsA(
          isA<UploadRejectedException>().having((e) => e.code, 'code', code),
        ),
      );
      await check('job-1', equals(jobNotFoundCode));
      await check(null, isNull);
    });

    test('a 410 on a PDF retake is not_retakeable', () async {
      await expectLater(
        _apiWith(_StubAdapter(status: 410, body: {})).submitPdf(
          details: const ScoreDetails(title: 'Ave'),
          pdfPath: page1,
          replacesJobId: 'job-1',
        ),
        throwsA(
          isA<UploadRejectedException>().having(
            (e) => e.code,
            'code',
            notRetakeableCode,
          ),
        ),
      );
    });

    test('an error envelope keeps code, field and page', () async {
      final adapter = _StubAdapter(
        status: 415,
        body: {
          'success': false,
          'error': {
            'code': 'unsupported_file_type',
            'message': 'nope',
            'pageIndex': 1,
          },
        },
      );
      await expectLater(
        _apiWith(adapter).submitImages(
          details: const ScoreDetails(title: 'Ave'),
          imagePaths: [page1, page2],
        ),
        throwsA(
          isA<UploadRejectedException>()
              .having((e) => e.statusCode, 'status', 415)
              .having((e) => e.code, 'code', 'unsupported_file_type')
              .having((e) => e.pageIndex, 'pageIndex', 1),
        ),
      );
    });

    test('401 is session expiry', () async {
      await expectLater(
        _apiWith(_StubAdapter(status: 401, body: {})).submitPdf(
          details: const ScoreDetails(title: 'Ave'),
          pdfPath: pdf,
        ),
        throwsA(isA<UploadSessionExpiredException>()),
      );
    });

    test('429 reads Retry-After from the header', () async {
      await expectLater(
        _apiWith(
          _StubAdapter(
            status: 429,
            body: {
              'error': {'code': 'queue_full'},
            },
            headers: {
              'retry-after': ['45'],
            },
          ),
        ).submitImages(
          details: const ScoreDetails(title: 'Ave'),
          imagePaths: [page1],
        ),
        throwsA(
          isA<UploadRejectedException>().having(
            (e) => e.retryAfter,
            'retryAfter',
            const Duration(seconds: 45),
          ),
        ),
      );
    });

    test('a proxy 413 HTML page is request_too_large', () async {
      await expectLater(
        _apiWith(_StubAdapter(status: 413, rawBody: '<html>Too Large</html>'))
            .submitImages(
              details: const ScoreDetails(title: 'Ave'),
              imagePaths: [page1],
            ),
        throwsA(
          isA<UploadRejectedException>().having(
            (e) => e.code,
            'code',
            'request_too_large',
          ),
        ),
      );
    });

    test('a page file gone from disk is a typed failure naming it', () async {
      final adapter = _StubAdapter();
      await expectLater(
        _apiWith(adapter).submitImages(
          details: const ScoreDetails(title: 'Ave'),
          imagePaths: [page1, '${temp.path}/gone.jpg'],
        ),
        throwsA(
          isA<UploadFileMissingException>().having(
            (e) => e.pageIndex,
            'pageIndex',
            1,
          ),
        ),
      );
      expect(adapter.requests, 0);
    });

    test('a PDF gone from disk is a typed failure with no page', () async {
      await expectLater(
        _apiWith(_StubAdapter()).submitPdf(
          details: const ScoreDetails(title: 'Ave'),
          pdfPath: '${temp.path}/gone.pdf',
        ),
        throwsA(
          isA<UploadFileMissingException>().having(
            (e) => e.pageIndex,
            'pageIndex',
            isNull,
          ),
        ),
      );
    });

    test('uploads have a send timeout and honour cancel', () async {
      final adapter = _StubAdapter(holdUntilCancelled: true);
      final token = CancelToken();
      final submit = _apiWith(adapter).submitImages(
        details: const ScoreDetails(title: 'Ave'),
        imagePaths: [page1],
        cancelToken: token,
      );
      // Cancel mid-request, not before it starts.
      while (adapter.lastRequest == null) {
        await Future<void>.delayed(const Duration(milliseconds: 1));
      }
      token.cancel();
      await expectLater(submit, throwsA(isA<UploadCancelledException>()));
      expect(adapter.lastRequest!.sendTimeout, ApiConfig.uploadSendTimeout);
    });

    test('a 202 without data.jobId is a rejection, not a crash', () async {
      await expectLater(
        _apiWith(_StubAdapter(body: {'data': {}})).submitImages(
          details: const ScoreDetails(title: 'Ave'),
          imagePaths: [page1],
        ),
        throwsA(isA<UploadRejectedException>()),
      );
    });
  });

  group('resubmitPage (PIYA-116, PIYA-207 AC7)', () {
    const replaced = {
      'data': {'replacementJobId': 'job-8', 'jobId': 'job-7'},
      'success': true,
      'status': 202,
    };

    test('sends one "page" part and a 0-based pageIndex', () async {
      final adapter = _StubAdapter(body: replaced);
      final job = await _apiWith(adapter)
          .resubmitPage(jobId: 'job-7', pageIndex: 1, imagePath: page1);
      expect(job.replacementJobId, 'job-8');
      expect(job.originalJobId, 'job-7');
      expect(job.pageIndex, 1);
      final request = adapter.lastRequest!;
      expect(request.path, ApiConfig.resubmitPagePath('job-7'));
      expect(request.method, 'POST');
      final form = request.data as FormData;
      expect(form.fields.map((e) => '${e.key}=${e.value}'), ['pageIndex=1']);
      expect(form.files.single.key, 'page');
      expect(form.files.single.value.filename, 'page-2.jpg');
    });

    test('404 and 409 without a code get the retake codes', () async {
      for (final (status, code) in [
        (404, jobNotFoundCode),
        (409, pageNotRetakeableCode),
      ]) {
        await expectLater(
          _apiWith(_StubAdapter(status: status, body: {}))
              .resubmitPage(jobId: 'j', pageIndex: 0, imagePath: page1),
          throwsA(
            isA<UploadRejectedException>().having((e) => e.code, 'code', code),
          ),
        );
      }
    });

    test('whole-score retake (PIYA-101 AC12): bare 404/409 get codes, '
        '410 is a dead retake, a sent code is kept', () {
      String? code(int status, [String? sent]) =>
          HttpScoreUploadApi.wholeRetakeRejection(
            UploadRejectedException(statusCode: status, code: sent),
          ).code;
      expect(code(404), jobNotFoundCode);
      expect(code(409), notRetakeableCode);
      expect(code(410), notRetakeableCode);
      expect(code(410, jobSupersededCode), notRetakeableCode);
      expect(code(409, retakeInProgressCode), retakeInProgressCode);
      expect(code(400, 'title_too_long'), 'title_too_long');
    });

    test('a server code is kept as sent', () {
      final kept = HttpScoreUploadApi.resubmitRejection(
        const UploadRejectedException(statusCode: 409, code: 'queue_full'),
      );
      expect(kept.code, 'queue_full');
    });

    test('an answer without replacementJobId is a rejection', () {
      expect(
        () => HttpScoreUploadApi.parseResubmittedJob(
          {
            'data': {'jobId': 'j'},
          },
          'j',
          0,
        ),
        throwsA(isA<UploadRejectedException>()),
      );
    });
  });

  group('parseSubmittedJob / rejectionFrom', () {
    test('missing pageCount and status get safe defaults', () {
      final job = HttpScoreUploadApi.parseSubmittedJob({
        'data': {'jobId': 'j'},
      });
      expect(job.pageCount, isNull);
      expect(job.status, 'queued');
      expect(job.scoreId, isNull);
    });

    test('scoreId is read when the server sends one (PIYA-218)', () {
      final job = HttpScoreUploadApi.parseSubmittedJob({
        'data': {'jobId': 'j', 'scoreId': 41},
      });
      expect(job.scoreId, 41);
      final bad = HttpScoreUploadApi.parseSubmittedJob({
        'data': {'jobId': 'j', 'scoreId': '41'},
      });
      expect(bad.scoreId, isNull);
    });

    test('retryAfterSeconds in the body wins over the header', () {
      final failure = HttpScoreUploadApi.rejectionFrom(
        Response(
          requestOptions: RequestOptions(),
          statusCode: 429,
          data: {
            'error': {'code': 'rate_limited', 'retryAfterSeconds': 12},
          },
          headers: Headers.fromMap({
            'retry-after': ['99'],
          }),
        ),
      );
      expect(
        (failure as UploadRejectedException).retryAfter,
        const Duration(seconds: 12),
      );
    });

    test('no response at all is a rejection with no status', () {
      final failure = HttpScoreUploadApi.rejectionFrom(null);
      expect(failure, isA<UploadRejectedException>());
      expect((failure as UploadRejectedException).statusCode, isNull);
    });
  });

  group('FakeScoreUploadApi', () {
    const ok = 'singer@example.com';
    const flaky = 'singer${FakeScoreLibraryApi.flakyDomain}';

    (FakeScoreUploadApi, FakeScoreLibraryApi) build(String? account) {
      final storage = SessionStorage(
        FaultySecureStorage({'session_token': ?account}),
      );
      String? lookup(String token) => token;
      final library = FakeScoreLibraryApi(
        sessionStorage: storage,
        accountForToken: lookup,
        latency: Duration.zero,
      );
      return (
        FakeScoreUploadApi(
          sessionStorage: storage,
          accountForToken: lookup,
          library: library,
          latency: Duration.zero,
        ),
        library,
      );
    }

    test('a submit adds the score to the library', () async {
      final (upload, library) = build(ok);
      final job = await upload.submitImages(
        details: const ScoreDetails(title: ' Ave ', arranger: 'Schubert'),
        imagePaths: const ['a', 'b'],
      );
      expect(job.jobId, startsWith('fake-job-'));
      final scores = await library.fetchLibrary();
      expect(scores.last.title, 'Ave');
      expect(scores.last.arranger, 'Schubert');
      expect(scores.last.pageCount, 2);
    });

    test('no account is session expiry', () async {
      final (upload, _) = build(null);
      await expectLater(
        upload.submitPdf(
          details: const ScoreDetails(title: 'A'),
          pdfPath: 'p',
        ),
        throwsA(isA<UploadSessionExpiredException>()),
      );
    });

    test('flaky accounts cycle 429, offline, 415, then success', () async {
      final (upload, _) = build(flaky);
      Future<SubmittedJob> submit() => upload.submitImages(
        details: const ScoreDetails(title: 'A'),
        imagePaths: const ['a'],
      );
      await expectLater(
        submit(),
        throwsA(
          isA<UploadRejectedException>().having(
            (e) => e.code,
            'code',
            'queue_full',
          ),
        ),
      );
      await expectLater(submit(), throwsA(isA<UploadNetworkException>()));
      await expectLater(
        submit(),
        throwsA(
          isA<UploadRejectedException>().having((e) => e.pageIndex, 'page', 0),
        ),
      );
      expect((await submit()).status, 'queued');
    });
  });
}
