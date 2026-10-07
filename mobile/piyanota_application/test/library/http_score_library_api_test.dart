import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/config/api_config.dart';
import 'package:piyanota_application/services/score_library_api.dart';
import 'package:piyanota_application/services/session_storage.dart';

import '../auth/auth_test_harness.dart';

/// Returns one canned response (or throws a connection error) for every
/// request, recording the last request so path/headers can be checked.
class _StubAdapter implements HttpClientAdapter {
  _StubAdapter({this.status = 200, this.body, this.connectionFails = false});

  final int status;
  final Object? body;
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

const _token = 'sess_a1b2c3d4';

HttpScoreLibraryApi _apiWith(_StubAdapter adapter, {String? token = _token}) {
  final dio = Dio(BaseOptions(baseUrl: 'https://api.test'))
    ..httpClientAdapter = adapter;
  final storage = SessionStorage(
    FaultySecureStorage({'session_token': ?token}),
  );
  return HttpScoreLibraryApi(dio, storage);
}

const _listBody = {
  'data': {
    'scores': [
      {
        'scoreId': 101,
        'title': 'Bituin Walang Ningning',
        'lastAccessedAt': '2026-10-03T14:22:00Z',
        'thumbnailUrl': 'https://cdn.test/101.png',
      },
      {
        'scoreId': 102,
        'title': 'Paraiso',
        'lastProcessedAt': '2026-09-28T09:05:00Z',
        'thumbnailUrl': null,
      },
    ],
  },
  'success': true,
  'status': 200,
};

void main() {
  group('fetchLibrary (PIYA-308)', () {
    test('GETs the library path with the Bearer token and maps entries',
        () async {
      final adapter = _StubAdapter(body: _listBody);
      final scores = await _apiWith(adapter).fetchLibrary();

      expect(adapter.lastRequest?.method, 'GET');
      expect(adapter.lastRequest?.path, ApiConfig.scoreLibraryPath);
      expect(adapter.lastRequest?.headers['Authorization'], 'Bearer $_token');
      expect(adapter.lastRequest?.queryParameters, isEmpty);

      expect(scores.map((s) => s.scoreId), [101, 102]);
      expect(scores.first.title, 'Bituin Walang Ningning');
      expect(scores.first.lastActivityAt, DateTime.utc(2026, 10, 3, 14, 22));
      expect(scores.first.thumbnailUrl, 'https://cdn.test/101.png');
      // lastProcessedAt is accepted when lastAccessedAt is absent.
      expect(scores.last.lastActivityAt, DateTime.utc(2026, 9, 28, 9, 5));
    });

    test('sends a trimmed search parameter only when non-blank', () async {
      final adapter = _StubAdapter(body: _listBody);
      final api = _apiWith(adapter);

      await api.fetchLibrary(query: '  kubo ');
      expect(adapter.lastRequest?.queryParameters, {
        ApiConfig.scoreLibrarySearchParam: 'kubo',
      });

      await api.fetchLibrary(query: '   ');
      expect(adapter.lastRequest?.queryParameters, isEmpty);
    });

    test('an empty scores array is an empty list, not an error', () async {
      final adapter = _StubAdapter(body: {
        'data': {'scores': <Object>[]},
      });
      expect(await _apiWith(adapter).fetchLibrary(), isEmpty);
    });

    test('no stored token is a session error and sends nothing', () async {
      final adapter = _StubAdapter(body: _listBody);
      await expectLater(
        _apiWith(adapter, token: null).fetchLibrary(),
        throwsA(isA<SessionExpiredException>()),
      );
      expect(adapter.requests, 0);
    });

    test('401 maps to SessionExpiredException', () async {
      final adapter = _StubAdapter(status: 401, body: {'message': 'no'});
      await expectLater(
        _apiWith(adapter).fetchLibrary(),
        throwsA(isA<SessionExpiredException>()),
      );
    });

    test('500 maps to ScoreLibraryServerException', () async {
      final adapter = _StubAdapter(status: 500, body: {'message': 'boom'});
      await expectLater(
        _apiWith(adapter).fetchLibrary(),
        throwsA(isA<ScoreLibraryServerException>()),
      );
    });

    test('connection failure maps to ScoreLibraryNetworkException', () async {
      final adapter = _StubAdapter(connectionFails: true);
      await expectLater(
        _apiWith(adapter).fetchLibrary(),
        throwsA(isA<ScoreLibraryNetworkException>()),
      );
    });

    test('a body without data.scores is a server error', () async {
      final adapter = _StubAdapter(body: {'data': {'items': <Object>[]}});
      await expectLater(
        _apiWith(adapter).fetchLibrary(),
        throwsA(isA<ScoreLibraryServerException>()),
      );
    });

    test('entries without a valid scoreId are skipped; the rest load',
        () async {
      final adapter = _StubAdapter(body: {
        'data': {
          'scores': [
            {'scoreId': '101', 'title': 'string id'},
            {'title': 'no id'},
            'not an object',
            {'scoreId': 102, 'title': 'Paraiso'},
            // Every other field broken: still loads, just bare.
            {
              'scoreId': 103,
              'title': '',
              'lastAccessedAt': 'yesterday',
              'composer': 7,
              'pageCount': 'many',
              'thumbnailUrl': false,
            },
          ],
        },
      });
      final scores = await _apiWith(adapter).fetchLibrary();
      expect(scores.map((s) => s.scoreId), [102, 103]);
      final bare = scores.last;
      expect(bare.title, isNull);
      expect(bare.lastActivityAt, isNull);
      expect(bare.composer, isNull);
      expect(bare.pageCount, isNull);
      expect(bare.thumbnailUrl, isNull);
    });
  });

  group('deleteScore (PIYA-309)', () {
    test('DELETEs the score path with the Bearer token', () async {
      final adapter = _StubAdapter(body: {'message': 'Score deleted'});
      await _apiWith(adapter).deleteScore(102);

      expect(adapter.lastRequest?.method, 'DELETE');
      expect(adapter.lastRequest?.path, ApiConfig.scorePath(102));
      expect(adapter.lastRequest?.headers['Authorization'], 'Bearer $_token');
    });

    test('404 maps to ScoreNotFoundException', () async {
      final adapter = _StubAdapter(status: 404, body: {'message': 'nope'});
      await expectLater(
        _apiWith(adapter).deleteScore(999),
        throwsA(isA<ScoreNotFoundException>()),
      );
    });

    test('401 maps to SessionExpiredException', () async {
      final adapter = _StubAdapter(status: 401, body: {'message': 'no'});
      await expectLater(
        _apiWith(adapter).deleteScore(102),
        throwsA(isA<SessionExpiredException>()),
      );
    });

    test('connection failure maps to ScoreLibraryNetworkException', () async {
      final adapter = _StubAdapter(connectionFails: true);
      await expectLater(
        _apiWith(adapter).deleteScore(102),
        throwsA(isA<ScoreLibraryNetworkException>()),
      );
    });
  });
}
