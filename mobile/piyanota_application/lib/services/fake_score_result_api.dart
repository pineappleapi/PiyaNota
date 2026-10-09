import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../models/score_result.dart';
import 'demo/playback_demo.dart';
import 'fake_processing_api.dart';
import 'fake_score_library_api.dart';
import 'score_result_api.dart';
import 'session_storage.dart';

/// In-memory stand-in for PIYA-103 until Module 3 is deployed, scoped like
/// the other fakes:
///
/// - A score the signed-in account doesn't have is a 404.
/// - A score whose fake job hasn't completed (a fresh PIYA-206 submit) is
///   a 409.
/// - Accounts on [FakeScoreLibraryApi.flakyDomain] fail every odd fetch, so
///   the error/Retry state can be demoed.
/// - Every other score plays the same demo, generated on the device into
///   the cache dir (see [PlaybackDemo]; never a bundled asset, so release
///   builds, which never construct this class, carry none of it).
class FakeScoreResultApi implements ScoreResultApi {
  FakeScoreResultApi({
    required this._sessionStorage,
    required this._accountForToken,
    required this._library,
    this._processing,
    Future<PlaybackDemoFiles> Function()? demoFiles,
    this.latency = defaultLatency,
  }) : _writeDemo = demoFiles ?? _writeDemoToCache;

  static const Duration defaultLatency = Duration(milliseconds: 600);

  final SessionStorage _sessionStorage;
  final AccountForToken _accountForToken;
  final FakeScoreLibraryApi _library;
  final FakeProcessingApi? _processing;
  final Future<PlaybackDemoFiles> Function() _writeDemo;
  final Duration latency;
  final Map<String, int> _fetchCallsByAccount = {};
  Future<PlaybackDemoFiles>? _demo;

  static Future<PlaybackDemoFiles> _writeDemoToCache() async =>
      PlaybackDemo.writeTo(
        Directory('${(await getTemporaryDirectory()).path}/playback_demo'),
      );

  /// Generated once per app run (and reused from the cache dir after).
  /// A failed attempt is retried on the next fetch.
  Future<PlaybackDemoFiles> _demoFiles() =>
      _demo ??= _writeDemo().catchError((Object e) {
        _demo = null;
        throw e;
      });

  @override
  Future<ScoreResult> fetchResult(int scoreId) async {
    await Future<void>.delayed(latency);
    final token = await _sessionStorage.readToken();
    final account = token == null ? null : _accountForToken(token);
    if (account == null) throw const ScoreResultSessionExpiredException();
    if (account.endsWith(FakeScoreLibraryApi.flakyDomain)) {
      final count = (_fetchCallsByAccount[account] ?? 0) + 1;
      _fetchCallsByAccount[account] = count;
      if (count.isOdd) throw const ScoreResultServerException();
    }
    final score = _library.scoreFor(account: account, scoreId: scoreId);
    if (score == null) throw const ScoreResultNotFoundException();
    if (_processing?.hasUnfinishedJob(account: account, scoreId: scoreId) ??
        false) {
      throw const ScoreResultNotReadyException();
    }
    final demo = await _demoFiles();
    // The PIYA-103 envelope's `data`, through the real parser, so the fake
    // can't hand Playback something the server never could.
    return ScoreResult.fromJson({
      'jobId': 'fake-job-$scoreId',
      'scoreId': scoreId,
      'audioTracks': {
        for (final MapEntry(key: voice, value: uri) in demo.tracks.entries)
          voice.name: uri.toString(),
      },
      'scoreImages': [demo.page.toString()],
      'timingMetadataUrl': demo.timing.toString(),
      'review': {
        'reviewNeeded': true,
        'reasons': ['low_confidence'],
        'items': const <Object>[],
        'truncated': false,
      },
      // Not in PIYA-103 (proposed): see ScoreResult.pageSizes.
      'scoreImageSizes': [
        {'width': PlaybackDemo.pageWidth, 'height': PlaybackDemo.pageHeight},
      ],
      'arranger': ?score.arranger,
      // PIYA-103 AC8; the demo is rendered at this tempo.
      'tempoBpm': PlaybackDemo.bpm,
    });
  }

  @override
  Future<List<TimingEvent>> fetchTiming(Uri url) async {
    if (url.scheme != 'file') throw const ScoreResultNotFoundException();
    try {
      final text = await File.fromUri(url).readAsString();
      return parseTimingEvents(jsonDecode(text));
    } on FormatException {
      throw const ScoreResultServerException();
    } on FileSystemException {
      throw const ScoreResultNotFoundException();
    }
  }
}
