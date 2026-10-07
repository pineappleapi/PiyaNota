import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/api_config.dart';
import '../models/score_summary.dart';
import '../services/fake_score_library_api.dart';
import '../services/score_library_api.dart';
import 'auth_providers.dart';

/// Fake until Module 3 is deployed (see [ApiConfig.useFakeAuth]); PIYA-215
/// swaps nothing but this flag. Re-checks the startup validation for the
/// same reason [authApiProvider] does.
final scoreLibraryApiProvider = Provider<ScoreLibraryApi>((ref) {
  final sessionStorage = ref.watch(sessionStorageProvider);
  if (ApiConfig.useFakeAuth) {
    return FakeScoreLibraryApi(
      sessionStorage: sessionStorage,
      accountForToken: ref.watch(fakeAuthApiProvider).accountForToken,
    );
  }
  final configError = ApiConfig.configurationError();
  if (configError != null) throw StateError(configError);
  return HttpScoreLibraryApi(ref.watch(dioProvider), sessionStorage);
});

/// The signed-in user's full library (PIYA-308 with no search term).
///
/// autoDispose so the list is dropped when the Library leaves the tree
/// (e.g. on logout): a later login as a different account then fetches
/// fresh instead of briefly showing the previous user's scores (AC1).
/// Riverpod 3's automatic retry is disabled — a failed load must stay on
/// the error state until the user taps Retry (AC6), not loop silently.
final scoreLibraryProvider =
    AsyncNotifierProvider.autoDispose<ScoreLibraryController, List<ScoreSummary>>(
  ScoreLibraryController.new,
  retry: (_, _) => null,
);

class ScoreLibraryController extends AsyncNotifier<List<ScoreSummary>> {
  @override
  Future<List<ScoreSummary>> build() =>
      ref.watch(scoreLibraryApiProvider).fetchLibrary();

  /// AC6 retry. Resets to a plain loading state (no stale error kept
  /// alongside) so the screen shows the loading view, not the old error.
  Future<void> reload() async {
    state = const AsyncLoading();
    final result = await AsyncValue.guard(
      () => ref.read(scoreLibraryApiProvider).fetchLibrary(),
    );
    if (ref.mounted) state = result;
  }

  /// Deletes on the server first and removes the entry locally only once
  /// that succeeds (PIYA-215 AC2: not optimistic). A 404 also removes it —
  /// the server has confirmed it isn't in this library — then rethrows so
  /// the screen can say so. Every other failure leaves the list untouched
  /// and rethrows.
  Future<void> delete(int scoreId) async {
    try {
      await ref.read(scoreLibraryApiProvider).deleteScore(scoreId);
    } on ScoreNotFoundException {
      _removeLocally(scoreId);
      rethrow;
    }
    _removeLocally(scoreId);
  }

  void _removeLocally(int scoreId) {
    if (!ref.mounted) return;
    final current = state.value;
    if (current == null) return;
    state = AsyncData([
      for (final score in current)
        if (score.scoreId != scoreId) score,
    ]);
  }
}

/// Case-insensitive, partial title match (PIYA-205 AC3). Applied client-side
/// to the already-fetched list for now; PIYA-215 AC1 moves search to a
/// debounced PIYA-308 call, which must keep these same semantics.
List<ScoreSummary> filterScoresByTitle(
  List<ScoreSummary> scores,
  String query,
) {
  final needle = query.trim().toLowerCase();
  if (needle.isEmpty) return scores;
  return [
    for (final score in scores)
      if (score.title.toLowerCase().contains(needle)) score,
  ];
}
