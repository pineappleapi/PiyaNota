import 'dart:async';

import 'package:flutter/foundation.dart';
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
    AsyncNotifierProvider.autoDispose<
      ScoreLibraryController,
      List<ScoreSummary>
    >(ScoreLibraryController.new, retry: (_, _) => null);

class ScoreLibraryController extends AsyncNotifier<List<ScoreSummary>> {
  @override
  Future<List<ScoreSummary>> build() =>
      ref.watch(scoreLibraryApiProvider).fetchLibrary();

  Future<void>? _reloading;

  /// AC6 retry. Resets to a plain loading state (no stale error kept
  /// alongside) so the screen shows the loading view, not the old error.
  /// A second call while one is running joins it instead of fetching twice.
  Future<void> reload() => _reloading ??= _reload().whenComplete(() {
    _reloading = null;
  });

  Future<void> _reload() async {
    state = const AsyncLoading();
    final result = await AsyncValue.guard(
      () => ref.read(scoreLibraryApiProvider).fetchLibrary(),
    );
    if (ref.mounted) state = result;
  }

  /// Deletes [scoreId] on the server only. Callers remove the row with
  /// [removeLocally] once this succeeds (PIYA-215 AC2: not optimistic),
  /// after any exit animation.
  Future<void> deleteOnServer(int scoreId) =>
      ref.read(scoreLibraryApiProvider).deleteScore(scoreId);

  /// Records that the user opened [scoreId] for playback, moving it to the
  /// top of the library straight away.
  ///
  /// [ScoreLibraryApi.recordOpened] is a no-op for the real API (the server
  /// updates `last_accessed_at` on the Playback fetch, PIYA-308 AC8); the
  /// fake uses it to keep a refetch consistent. Its failure only costs the
  /// server-side date, never the open, so it is logged, not surfaced.
  void markOpened(int scoreId) {
    final now = DateTime.now().toUtc();
    unawaited(
      ref.read(scoreLibraryApiProvider).recordOpened(scoreId).catchError((
        Object e,
      ) {
        if (kDebugMode) debugPrint('Score open not recorded: $e');
      }),
    );
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
