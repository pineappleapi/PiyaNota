import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

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
  static const String _cachePrefix = 'score_library_cache_';

  /// Cache-first: a stored list renders at once (works with no network) and
  /// the server copy is fetched in the background. A failed background
  /// fetch never replaces the list. Only with nothing stored does a failed
  /// fetch surface as the error/Retry state.
  @override
  Future<List<ScoreSummary>> build() async {
    final api = ref.watch(scoreLibraryApiProvider);
    final cached = await _readCache();
    if (cached != null) {
      Future.microtask(() => _refresh(api));
      return cached;
    }
    final fresh = await api.fetchLibrary();
    unawaited(_writeCache(fresh));
    return fresh;
  }

  // Bumped by local delete/rename/open so an older in-flight refresh can't
  // overwrite them with a stale server copy.
  int _localEpoch = 0;

  Future<void> _refresh(ScoreLibraryApi api) async {
    final epoch = _localEpoch;
    try {
      final fresh = await api.fetchLibrary();
      if (!ref.mounted || epoch != _localEpoch) return;
      state = AsyncData(fresh);
      await _writeCache(fresh);
    } on SessionExpiredException catch (e, st) {
      // Retry can't fix a rejected token; the screen offers the login way out.
      if (ref.mounted) state = AsyncError(e, st);
    } on Object catch (e) {
      // Offline or server down: keep showing the stored list.
      if (kDebugMode) debugPrint('Library background refresh failed: $e');
    }
  }

  // Keyed by account email so a different login never sees another user's
  // scores. shortcut: stale entries of old accounts are never pruned; upgrade
  // if cache size matters.
  Future<String?> _cacheKey() async {
    final email = await ref.read(sessionStorageProvider).readEmail();
    return email == null ? null : '$_cachePrefix${email.toLowerCase()}';
  }

  Future<List<ScoreSummary>?> _readCache() async {
    try {
      final key = await _cacheKey();
      if (key == null) return null;
      final raw = (await SharedPreferences.getInstance()).getString(key);
      if (raw == null) return null;
      return [
        for (final item in jsonDecode(raw) as List<dynamic>)
          ScoreSummary.fromJson(item as Map<String, dynamic>),
      ];
    } on Object catch (e) {
      // A bad or unreadable cache must only cost the fast path.
      if (kDebugMode) debugPrint('Library cache unreadable: $e');
      return null;
    }
  }

  Future<void> _writeCache(List<ScoreSummary> scores) async {
    try {
      final key = await _cacheKey();
      if (key == null) return;
      await (await SharedPreferences.getInstance()).setString(
        key,
        jsonEncode([for (final s in scores) s.toJson()]),
      );
    } on Object catch (e) {
      if (kDebugMode) debugPrint('Library cache not written: $e');
    }
  }

  void _set(List<ScoreSummary> scores) {
    _localEpoch++;
    state = AsyncData(scores);
    unawaited(_writeCache(scores));
  }

  Future<void>? _reloading;

  /// AC6 retry. With nothing on screen it resets to a plain loading state;
  /// with a list already shown it refreshes quietly instead, so a failure
  /// keeps the list. A second call while one is running joins it.
  Future<void> reload() => _reloading ??= _reload().whenComplete(() {
    _reloading = null;
  });

  Future<void> _reload() async {
    final api = ref.read(scoreLibraryApiProvider);
    if (state.value != null) return _refresh(api);
    state = const AsyncLoading();
    final result = await AsyncValue.guard(api.fetchLibrary);
    if (!ref.mounted) return;
    state = result;
    if (result.value case final fresh?) unawaited(_writeCache(fresh));
  }

  /// Deletes [scoreId] on the server only. Callers remove the row with
  /// [removeLocally] once this succeeds (PIYA-215 AC2: not optimistic),
  /// after any exit animation.
  Future<void> deleteOnServer(int scoreId) =>
      ref.read(scoreLibraryApiProvider).deleteScore(scoreId);

  /// PIYA-205-V2.4 AC4: saves the edit, then swaps just that card's values
  /// in the loaded list — no refetch, so scroll position and the other
  /// cards are untouched. On failure the old values stay and the error
  /// reaches the caller.
  Future<void> updateOnServer(
    int scoreId, {
    required String title,
    String? arranger,
  }) async {
    final updated = await ref
        .read(scoreLibraryApiProvider)
        .updateScore(scoreId, title: title, arranger: arranger);
    if (!ref.mounted) return;
    // shortcut: a reload() that started before this save and finishes after
    // it can overwrite the edited card with the older server copy until the
    // next refresh; upgrade to a per-id version merge if reload ever becomes
    // user-triggerable mid-edit (today it is only the error-state Retry).
    final current = state.value;
    if (current == null) return;
    _set([
      for (final score in current)
        if (score.scoreId == scoreId)
          score.withDetails(
            title: updated.title ?? title,
            arranger: updated.arranger,
          )
        else
          score,
    ]);
  }

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
    _set([
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
    _set([
      for (final score in current)
        if (score.scoreId != scoreId) score,
    ]);
  }
}
