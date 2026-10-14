import '../models/library_entry.dart';
import '../models/score_summary.dart';
import 'fake_auth_api.dart';
import 'score_library_api.dart';
import 'session_storage.dart';

/// Resolves a session token to the account it was issued to, or null when
/// the token is unknown. Satisfied by `FakeAuthApi.accountForToken`.
typedef AccountForToken = String? Function(String token);

/// In-memory stand-in for PIYA-308/309 until Module 3 is deployed. Scopes
/// data by the account behind the stored session token, exactly as the real
/// API scopes by `userId` (PIYA-205 AC1):
///
/// - [demoEmail] starts with the three scores from the PIYA-205 mockup.
/// - Any other account (e.g. a fresh sign-up) starts empty — the AC4 state.
/// - Accounts on [flakyDomain] also start with the demo scores, but every
///   odd-numbered fetch and delete fails, so the error/retry state (AC6) and
///   the non-optimistic delete failure (PIYA-215 AC2) can be demoed.
/// - An unknown or missing token is a 401 ([SessionExpiredException]).
class FakeScoreLibraryApi implements ScoreLibraryApi {
  FakeScoreLibraryApi({
    required this._sessionStorage,
    required this._accountForToken,
    this.latency = defaultLatency,
    DateTime Function()? clock,
  }) : _clock = clock ?? DateTime.now;

  final DateTime Function() _clock;

  static const String demoEmail = FakeAuthApi.demoEmail;
  static const String flakyDomain = '@flaky.test';
  static const Duration defaultLatency = Duration(milliseconds: 800);

  /// The mockup's three scores, plus two incomplete entries so the
  /// broken-data handling (PIYA-308 client handling, 2026-10-08) is visible
  /// in the demo: one untitled, one with no arranger or page count. The
  /// last one has a Tenor that couldn't be read (PIYA-207 AC11/AC12 demo).
  static final List<ScoreSummary> demoScores = List.unmodifiable([
    ScoreSummary(
      scoreId: 101,
      title: 'Bituin Walang Ningning',
      lastActivityAt: DateTime.utc(2026, 10, 3, 14, 22),
      arranger: 'Robert Delgado',
      pageCount: 10,
    ),
    ScoreSummary(
      scoreId: 102,
      title: 'Paraiso',
      lastActivityAt: DateTime.utc(2026, 9, 28, 9, 5),
      arranger: 'Ryan Cayabyab',
      pageCount: 14,
    ),
    ScoreSummary(
      scoreId: 103,
      title: 'Bahay Kubo',
      lastActivityAt: DateTime.utc(2026, 9, 21, 18, 40),
      arranger: 'A.O. Veneracion/C.Borela',
      pageCount: 7,
    ),
    ScoreSummary(
      scoreId: 104,
      lastActivityAt: DateTime.utc(2026, 9, 30, 11, 15),
      pageCount: 2,
    ),
    ScoreSummary(
      scoreId: 105,
      title: 'Pasko Na Naman',
      lastActivityAt: DateTime.utc(2026, 9, 14, 16, 30),
    ),
    ScoreSummary(
      scoreId: 106,
      title: 'Ama Namin',
      lastActivityAt: DateTime.utc(2026, 9, 10, 8, 45),
      arranger: 'Bobby Enriquez',
      pageCount: 3,
    ),
  ]);

  final Duration latency;
  final SessionStorage _sessionStorage;
  final AccountForToken _accountForToken;
  final Map<String, List<ScoreSummary>> _scoresByAccount = {};
  final Map<String, int> _fetchCallsByAccount = {};
  final Map<String, int> _deleteCallsByAccount = {};

  @override
  Future<List<ScoreSummary>> fetchLibrary({String? query}) async {
    await Future<void>.delayed(latency);
    final account = await _currentAccount();
    if (_shouldFail(_fetchCallsByAccount, account)) {
      throw const ScoreLibraryServerException();
    }
    final needle = query?.trim().toLowerCase() ?? '';
    // Same semantics the real search parameter must have (PIYA-308 AC4).
    return [
      for (final score in _scoresFor(account))
        if (needle.isEmpty || scoreMatchesQuery(score, needle)) score,
    ];
  }

  /// Stands in for the server-side `last_accessed_at` update that PIYA-308
  /// AC8 puts on the real playback/score fetch, so a refetch of the fake
  /// agrees with the client's local bump. Silent for unknown ids or
  /// accounts.
  @override
  Future<void> recordOpened(int scoreId) async {
    final when = _clock().toUtc();
    final token = await _sessionStorage.readToken();
    final account = token == null ? null : _accountForToken(token);
    if (account == null) return;
    final scores = _scoresFor(account);
    final index = scores.indexWhere((score) => score.scoreId == scoreId);
    if (index != -1) {
      scores[index] = scores[index].copyWith(lastActivityAt: when);
    }
  }

  @override
  Future<void> deleteScore(int scoreId) async {
    await Future<void>.delayed(latency);
    final account = await _currentAccount();
    if (_shouldFail(_deleteCallsByAccount, account)) {
      throw const ScoreLibraryServerException();
    }
    final scores = _scoresFor(account);
    final before = scores.length;
    scores.removeWhere((score) => score.scoreId == scoreId);
    if (scores.length == before) throw const ScoreNotFoundException();
  }

  /// Stands in for the score row PIYA-101/310 creates with the job, so a
  /// fake submit (PIYA-206) shows up in the library. The new score gets the
  /// next free id and today's date, which is returned so the fake job can
  /// hand it back on `complete` (PIYA-207 AC8).
  int addSubmittedScore({
    required String account,
    required String title,
    required int? pageCount,
    String? arranger,
  }) {
    final scores = _scoresFor(account);
    final highest = scores.fold<int>(
      demoScores.last.scoreId,
      (highest, score) => score.scoreId > highest ? score.scoreId : highest,
    );
    final scoreId = highest + 1;
    scores.add(
      ScoreSummary(
        scoreId: scoreId,
        title: title,
        lastActivityAt: _clock().toUtc(),
        arranger: arranger,
        pageCount: pageCount,
      ),
    );
    return scoreId;
  }

  /// Stands in for the placeholder score a cancelled scan leaves behind
  /// being removed (scan-status spec §3). Silent if it's already gone.
  void removeSubmittedScore({required String account, required int scoreId}) {
    _scoresFor(account).removeWhere((score) => score.scoreId == scoreId);
  }

  /// [scoreId] as [account] sees it, or null if that account has no such
  /// score. Lets the fake PIYA-103 result scope by account like the real
  /// one and reuse the entry's arranger.
  ScoreSummary? scoreFor({required String account, required int scoreId}) {
    for (final score in _scoresFor(account)) {
      if (score.scoreId == scoreId) return score;
    }
    return null;
  }

  Future<String> _currentAccount() async {
    final token = await _sessionStorage.readToken();
    final account = token == null ? null : _accountForToken(token);
    if (account == null) throw const SessionExpiredException();
    return account;
  }

  List<ScoreSummary> _scoresFor(String account) {
    return _scoresByAccount.putIfAbsent(account, () {
      final seeded = account == demoEmail || account.endsWith(flakyDomain);
      return seeded ? [...demoScores] : <ScoreSummary>[];
    });
  }

  bool _shouldFail(Map<String, int> calls, String account) {
    if (!account.endsWith(flakyDomain)) return false;
    final count = (calls[account] ?? 0) + 1;
    calls[account] = count;
    return count.isOdd;
  }
}
