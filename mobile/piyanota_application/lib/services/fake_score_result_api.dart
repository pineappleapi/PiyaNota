import 'dart:convert';

import 'package:flutter/services.dart' show AssetBundle, rootBundle;

import '../models/score_result.dart';
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
/// - Every other score plays the same bundled demo (assets/demo/, made by
///   tool/generate_playback_demo.py): one real preprocessed page with
///   synthesized audio whose notes do NOT match the printed ones; only the
///   indicator's bar and staff positions are real.
class FakeScoreResultApi implements ScoreResultApi {
  FakeScoreResultApi({
    required this._sessionStorage,
    required this._accountForToken,
    required this._library,
    this._processing,
    AssetBundle? bundle,
    this.latency = defaultLatency,
  }) : _bundle = bundle ?? rootBundle;

  static const Duration defaultLatency = Duration(milliseconds: 600);

  static const String _demo = 'assets/demo';
  static const List<String> _voices = ['soprano', 'alto', 'tenor', 'bass'];

  /// The demo page's pixel size; generate_playback_demo.py checks it.
  static const int demoPageWidth = 1300;
  static const int demoPageHeight = 1575;

  final SessionStorage _sessionStorage;
  final AccountForToken _accountForToken;
  final FakeScoreLibraryApi _library;
  final FakeProcessingApi? _processing;
  final AssetBundle _bundle;
  final Duration latency;
  final Map<String, int> _fetchCallsByAccount = {};

  static Uri _asset(String path) => Uri.parse('asset:///$_demo/$path');

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
    // The PIYA-103 envelope's `data`, through the real parser, so the fake
    // can't hand Playback something the server never could.
    return ScoreResult.fromJson({
      'jobId': 'fake-job-$scoreId',
      'scoreId': scoreId,
      'audioTracks': {
        for (final voice in _voices) voice: _asset('$voice.mp3').toString(),
      },
      'scoreImages': [_asset('score_page_1.png').toString()],
      'timingMetadataUrl': _asset('timing.json').toString(),
      'review': {
        'reviewNeeded': true,
        'reasons': ['low_confidence'],
        'items': const <Object>[],
        'truncated': false,
      },
      // Not in PIYA-103 (proposed): see ScoreResult.pageSizes / composer.
      'scoreImageSizes': [
        {'width': demoPageWidth, 'height': demoPageHeight},
      ],
      'composer': ?score.composer,
    });
  }

  @override
  Future<List<TimingEvent>> fetchTiming(Uri url) async {
    if (url.scheme != 'asset') throw const ScoreResultNotFoundException();
    try {
      final text = await _bundle.loadString(url.path.substring(1));
      return parseTimingEvents(jsonDecode(text));
    } on FormatException {
      throw const ScoreResultServerException();
    }
  }
}
