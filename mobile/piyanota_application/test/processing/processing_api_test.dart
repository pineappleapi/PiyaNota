import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/services/session_storage.dart';

import '../auth/auth_test_harness.dart';

class _StubAdapter implements HttpClientAdapter {
  _StubAdapter({this.status = 200, this.body, this.connectionFails = false});

  final int status;
  final Object? body;
  final bool connectionFails;
  RequestOptions? lastRequest;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    lastRequest = options;
    if (connectionFails) {
      throw DioException.connectionError(
        requestOptions: options,
        reason: 'Simulated offline',
      );
    }
    return ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

HttpProcessingApi _api(_StubAdapter adapter, {String? token = 'sess_t'}) {
  final dio = Dio(BaseOptions(baseUrl: 'https://api.test'))
    ..httpClientAdapter = adapter;
  return HttpProcessingApi(
    dio,
    SessionStorage(FaultySecureStorage({'session_token': ?token})),
  );
}

Map<String, Object?> _envelope(Map<String, Object?> data) => {
  'success': true,
  'status': 200,
  'data': data,
};

void main() {
  group('ProcessingStatus.fromJson', () {
    test('reads the PIYA-102 example', () {
      final s = ProcessingStatus.fromJson({
        'jobId': 'job-1',
        'status': 'transcribing',
        'currentPage': 2,
        'totalPages': 3,
        'percentComplete': 54.6,
        'estimatedRemainingSeconds': 71.2,
      });
      expect(s.stage, ProcessingStage.transcribing);
      expect(s.currentPage, 2);
      expect(s.totalPages, 3);
      expect(s.percentComplete, 55);
      expect(s.estimatedRemainingSeconds, 72);
      expect(s.failureReason, isNull);
      expect(s.scoreId, isNull);
    });

    test('every stage string maps; an unknown one keeps polling', () {
      const pairs = {
        'queued': ProcessingStage.queued,
        'preprocessing': ProcessingStage.preprocessing,
        'detecting_staff': ProcessingStage.detectingStaff,
        'transcribing': ProcessingStage.transcribing,
        'reconstructing': ProcessingStage.reconstructing,
        'synthesizing': ProcessingStage.synthesizing,
        'complete': ProcessingStage.complete,
        'failed': ProcessingStage.failed,
        'cancelled': ProcessingStage.cancelled,
        'aligning_lyrics': ProcessingStage.unknown,
      };
      for (final MapEntry(:key, :value) in pairs.entries) {
        expect(ProcessingStatus.fromJson({'status': key}).stage, value);
      }
      expect(ProcessingStage.unknown.isTerminal, isFalse);
    });

    test('a missing or non-string status is a FormatException', () {
      expect(() => ProcessingStatus.fromJson({}), throwsFormatException);
      expect(
        () => ProcessingStatus.fromJson({'status': 3}),
        throwsFormatException,
      );
    });

    test('broken optional fields drop to null instead of failing', () {
      final s = ProcessingStatus.fromJson({
        'status': 'transcribing',
        'currentPage': '2',
        'totalPages': 0,
        'percentComplete': 'half',
        'estimatedRemainingSeconds': -5,
        'scoreId': -1,
      });
      expect(s.currentPage, isNull);
      expect(s.totalPages, isNull);
      expect(s.percentComplete, isNull);
      expect(s.estimatedRemainingSeconds, isNull);
      expect(s.scoreId, isNull);
    });

    test('percent is clamped; page past the total hides both', () {
      final s = ProcessingStatus.fromJson({
        'status': 'transcribing',
        'percentComplete': 140,
        'currentPage': 4,
        'totalPages': 3,
      });
      expect(s.percentComplete, 100);
      expect(s.currentPage, isNull);
      expect(s.totalPages, isNull);
    });

    test('failure reason and page are read only when failed', () {
      final f = ProcessingStatus.fromJson({
        'status': 'failed',
        'failureReason': 'no_staff_detected',
        'pageIndex': 1,
      });
      expect(f.failureReason, FailureReason.noStaffDetected);
      expect(f.failedPageIndex, 1);

      final r = ProcessingStatus.fromJson({
        'status': 'transcribing',
        'failureReason': 'no_staff_detected',
        'pageIndex': 1,
      });
      expect(r.failureReason, isNull);
      expect(r.failedPageIndex, isNull);

      final u = ProcessingStatus.fromJson({
        'status': 'failed',
        'failureReason': 'cosmic_rays',
        'pageIndex': -1,
      });
      expect(u.failureReason, FailureReason.unknown);
      expect(u.failedPageIndex, isNull);
      expect(
        ProcessingStatus.fromJson({'status': 'failed'}).failureReason,
        FailureReason.unknown,
      );
    });

    test('every failure code maps; only page problems are retakeable', () {
      const retakeable = {
        'preprocessing_error',
        'no_staff_detected',
        'ambiguous_staff_count',
      };
      for (final code in [
        ...retakeable,
        'unsupported_staff_layout',
        'incomplete_voice_sequence',
        'stage_timeout',
        'server_restart',
      ]) {
        final reason = FailureReason.fromApi(code);
        expect(reason, isNot(FailureReason.unknown), reason: code);
        expect(reason.isRetakeable, retakeable.contains(code), reason: code);
      }
    });

    test('scoreId is read when present (PIYA-207 contract ask)', () {
      expect(
        ProcessingStatus.fromJson({'status': 'complete', 'scoreId': 12})
            .scoreId,
        12,
      );
    });
  });

  group('HttpProcessingApi', () {
    test('polls GET /jobs/{id} with the bearer token', () async {
      final adapter = _StubAdapter(
        body: _envelope({'status': 'queued', 'percentComplete': 0}),
      );
      final status = await _api(adapter).fetchStatus('job 1');
      expect(status.stage, ProcessingStage.queued);
      expect(adapter.lastRequest!.method, 'GET');
      expect(adapter.lastRequest!.uri.path, endsWith('/job%201'));
      expect(adapter.lastRequest!.headers['Authorization'], 'Bearer sess_t');
    });

    test('cancel POSTs to /cancel', () async {
      final adapter = _StubAdapter(body: _envelope({'status': 'cancelled'}));
      await _api(adapter).cancelJob('job-1');
      expect(adapter.lastRequest!.method, 'POST');
      expect(adapter.lastRequest!.uri.path, endsWith('/job-1/cancel'));
    });

    test('no token is a session expiry without a request', () async {
      final adapter = _StubAdapter(body: _envelope({'status': 'queued'}));
      await expectLater(
        _api(adapter, token: null).fetchStatus('job-1'),
        throwsA(isA<ProcessingSessionExpiredException>()),
      );
      expect(adapter.lastRequest, isNull);
    });

    test('HTTP errors map to typed exceptions', () async {
      final cases = <int, Matcher>{
        401: isA<ProcessingSessionExpiredException>(),
        404: isA<ProcessingJobNotFoundException>(),
        409: isA<ProcessingConflictException>(),
        500: isA<ProcessingServerException>(),
        503: isA<ProcessingServerException>(),
        418: isA<ProcessingServerException>(),
      };
      for (final MapEntry(key: status, value: matcher) in cases.entries) {
        await expectLater(
          _api(_StubAdapter(status: status, body: {})).fetchStatus('j'),
          throwsA(matcher),
          reason: '$status',
        );
      }
    });

    test('no connection is a network error', () async {
      await expectLater(
        _api(_StubAdapter(connectionFails: true)).fetchStatus('j'),
        throwsA(isA<ProcessingNetworkException>()),
      );
    });

    test('a body without data.status is a server error', () async {
      for (final body in <Object?>[
        null,
        'oops',
        {'data': null},
        {'data': <String, Object?>{}},
        {
          'data': {'status': 7},
        },
      ]) {
        expect(
          () => HttpProcessingApi.parseStatus(body),
          throwsA(isA<ProcessingServerException>()),
          reason: '$body',
        );
      }
    });

    test('timeouts are network errors; cancel and unknown are server', () {
      final options = RequestOptions(path: '/');
      for (final type in [
        DioExceptionType.connectionTimeout,
        DioExceptionType.sendTimeout,
        DioExceptionType.receiveTimeout,
        DioExceptionType.connectionError,
      ]) {
        expect(
          HttpProcessingApi.mapDioError(
            DioException(requestOptions: options, type: type),
          ),
          isA<ProcessingNetworkException>(),
        );
      }
      for (final type in [
        DioExceptionType.cancel,
        DioExceptionType.unknown,
        DioExceptionType.badCertificate,
      ]) {
        expect(
          HttpProcessingApi.mapDioError(
            DioException(requestOptions: options, type: type),
          ),
          isA<ProcessingServerException>(),
        );
      }
    });
  });
}
