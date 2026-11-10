import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/local_submission.dart';

/// Keeps the user's submissions on the device (job-lifecycle plan, Task 3),
/// so a score being uploaded or converted stays in the library after the app
/// is closed.
///
/// SharedPreferences like [ScanJobStore]: nothing here is a secret (no token,
/// no URL). No widget or Riverpod dependency, so a background isolate can use
/// it directly. `load(fresh: true)` reloads first, so a write by another isolate
/// and the foreground skips it because its own cache is already current
/// and a reload would resurrect keys another store just removed.
/// Writes ([update], [markDismissed], [clear]) queue behind each other inside
/// one isolate. shortcut: not atomic across isolates, so the foreground and
/// the headless background run writing at the same moment can lose one
/// update; the background run stops when the app comes to the foreground
/// (BackgroundCompletion's cancel flag) which makes that rare, and the next
/// reconcile repairs a lost row. Upgrade to a per-row key if it ever shows.
///
/// Every call swallows and logs storage errors: a phone that can't save this
/// must still be able to submit, it only forgets the row on restart.
class LocalSubmissionStore {
  const LocalSubmissionStore();

  @visibleForTesting
  static const String storageKey = 'local_submissions_v1';

  Future<List<LocalSubmission>> load({bool fresh = false}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (fresh) await prefs.reload();
      final raw = prefs.getString(storageKey);
      return raw == null ? const [] : decode(raw);
    } on Object catch (e) {
      debugPrint('Local submissions not restored: $e');
      return const [];
    }
  }

  Future<void> save(Iterable<LocalSubmission> rows) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(storageKey, encode(rows));
    } on Object catch (e) {
      debugPrint('Local submissions not saved: $e');
    }
  }

  /// Load, change and save in one go, so reconcile applies its result to
  /// the rows as they are NOW (a row dismissed or added while it waited on
  /// the network is not overwritten). Returns what was saved.
  ///
  /// Calls queue behind each other inside this isolate, so two started in the
  /// same tick cannot both read the old list and drop one change.
  Future<List<LocalSubmission>> update(
    List<LocalSubmission> Function(List<LocalSubmission> current) change, {
    bool fresh = false,
  }) {
    return _enqueue(() async {
      final next = change(await load(fresh: fresh));
      await save(next);
      return next;
    });
  }

  Future<T> _enqueue<T>(Future<T> Function() job) {
    final zone = Zone.current;
    final run = (_updates[zone] ?? Future<void>.value()).then((_) => job());
    _updates[zone] = run.then<void>((_) {}, onError: (Object _) {});
    return run;
  }

  // Keyed by zone: a queue left pending in a finished test's fake-async zone
  // would otherwise block every later update. The app runs in one zone.
  static final Expando<Future<void>> _updates = Expando<Future<void>>();

  @visibleForTesting
  static const String dismissedKey = 'dismissed_submissions_v1';

  /// Ids (clientSubmissionId or jobId) the user dismissed, with when. Kept so
  /// a server job that reappears in `GET /api/jobs` is not turned back into a
  /// row the user already removed.
  Future<Map<String, DateTime>> loadDismissed({bool fresh = false}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (fresh) await prefs.reload();
      final raw = prefs.getString(dismissedKey);
      if (raw == null) return {};
      final json = jsonDecode(raw);
      if (json is! Map) return {};
      final out = <String, DateTime>{};
      for (final e in json.entries) {
        final at = e.value is String
            ? DateTime.tryParse(e.value as String)
            : null;
        if (e.key is String && at != null) out[e.key as String] = at;
      }
      return out;
    } on Object catch (e) {
      debugPrint('Dismissed submissions not restored: $e');
      return {};
    }
  }

  /// Adds [ids] as dismissed at [now] and drops entries older than
  /// [retention] (the server list forgets finished jobs after that anyway).
  /// On the same queue as [update] and [clear], so a dismissal made while a
  /// reconcile is writing is neither lost nor written back after a wipe.
  Future<void> markDismissed(
    Iterable<String> ids,
    DateTime now, {
    required Duration retention,
    bool fresh = false,
  }) => _enqueue(() async {
    try {
      final all = await loadDismissed(fresh: fresh);
      for (final id in ids) {
        all[id] = now;
      }
      all.removeWhere((_, at) => now.difference(at) > retention);
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(
        dismissedKey,
        jsonEncode({
          for (final e in all.entries) e.key: e.value.toUtc().toIso8601String(),
        }),
      );
    } on Object catch (e) {
      debugPrint('Dismissed submissions not saved: $e');
    }
  });

  /// Queued behind any [update] already running, so one that loaded rows
  /// before logout cannot write them back after the wipe.
  Future<void> clear() => _enqueue(() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(storageKey);
      await prefs.remove(dismissedKey);
    } on Object catch (e) {
      debugPrint('Local submissions not cleared: $e');
    }
  });

  static String encode(Iterable<LocalSubmission> rows) =>
      jsonEncode([for (final row in rows) row.toJson()]);

  /// Drops any entry it can't read rather than failing the whole restore.
  static List<LocalSubmission> decode(String raw) {
    final Object? list;
    try {
      list = jsonDecode(raw);
    } on FormatException catch (e) {
      debugPrint('Stored submissions unreadable: $e');
      return const [];
    }
    if (list is! List) return const [];
    return [
      for (final entry in list)
        if (entry is Map<String, dynamic>) ?LocalSubmission.fromJson(entry),
    ];
  }
}
