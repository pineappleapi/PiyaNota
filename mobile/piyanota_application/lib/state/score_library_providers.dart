import 'dart:async';

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

/// The signed-in user's full library (PIYA-308 with no search term), in
/// server order. The screen sorts and labels it with `buildLibraryEntries`.
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
      await deleteOnServer(scoreId);
    } on ScoreNotFoundException {
      removeLocally(scoreId);
      rethrow;
    }
    removeLocally(scoreId);
  }

  /// The server half of [delete], for callers that animate the row out
  /// before calling [removeLocally] themselves (the Library's swipe and
  /// trash paths). Never touches local state.
  Future<void> deleteOnServer(int scoreId) =>
      ref.read(scoreLibraryApiProvider).deleteScore(scoreId);

  /// Records that the user opened [scoreId] for playback, moving it to the
  /// top of the library straight away.
  ///
  /// Local only for the real API: the server updates `last_accessed_at`
  /// itself when Playback fetches the score (PIYA-308 AC8), so there is
  /// deliberately no HTTP call here. The fake has no Playback fetch, so it
  /// is told directly to keep a refetch consistent.
  void markOpened(int scoreId) {
    final now = DateTime.now().toUtc();
    final api = ref.read(scoreLibraryApiProvider);
    if (api is FakeScoreLibraryApi) {
      unawaited(api.markOpened(scoreId, now));
    }
    final current = state.value;
    if (current == null) return;
    state = AsyncData([
      for (final score in current)
        if (score.scoreId == scoreId)
          score.copyWith(lastActivityAt: now)
        else
          score,
    ]);
  }

  /// Drops [scoreId] from the list. Only call this once the server has
  /// confirmed the deletion (200) or reported the score gone (404).
  void removeLocally(int scoreId) {
    if (!ref.mounted) return;
    final current = state.value;
    if (current == null) return;
    state = AsyncData([
      for (final score in current)
        if (score.scoreId != scoreId) score,
    ]);
  }
}
