import 'dart:io';

import 'package:flutter/foundation.dart';

import '../../models/capture_session.dart';

/// Deletes Capture's working files. Failures are logged, never thrown:
/// a leftover temp file must not break capturing or sending.
abstract interface class CaptureFileStore {
  Future<void> delete(String path);

  /// Deletes files in the capture folder last modified before [before]:
  /// leftovers from an earlier session that crashed or was killed.
  Future<void> clearStale(DateTime before);
}

class DiskCaptureFileStore implements CaptureFileStore {
  DiskCaptureFileStore(this._directory);

  final Future<Directory> Function() _directory;

  @override
  Future<void> delete(String path) async {
    try {
      await File(path).delete();
    } on PathNotFoundException {
      // Already gone (Android may clear the temp folder): nothing to do.
    } on FileSystemException catch (e) {
      debugPrint('Capture file not deleted: ${e.path}: ${e.message}');
    }
  }

  @override
  Future<void> clearStale(DateTime before) async {
    try {
      final dir = await _directory();
      await for (final entity in dir.list(followLinks: false)) {
        if (entity is! File) continue;
        try {
          if ((await entity.lastModified()).isBefore(before)) {
            await entity.delete();
          }
        } on FileSystemException catch (e) {
          debugPrint('Stale capture file not deleted: ${e.path}: $e');
        }
      }
    } on Exception catch (e) {
      debugPrint('Stale capture files not cleared: $e');
    }
  }
}

/// Tracks which working files Capture created, and deletes each one once
/// nothing refers to it any more: not the session, and not a removed page
/// still waiting on Undo ([sweep]'s `keep`).
class CaptureFileLedger {
  CaptureFileLedger(this._delete);

  final void Function(String path) _delete;
  final Set<String> _owned = {};

  @visibleForTesting
  Set<String> get owned => Set.unmodifiable(_owned);

  void own(String path) => _owned.add(path);

  /// Deletes owned files that [session] and [keep] no longer reference.
  void sweep(CaptureSession session, {Iterable<String> keep = const []}) {
    final referenced = {for (final item in session.items) item.path, ...keep};
    final orphans = _owned.where((p) => !referenced.contains(p)).toList();
    for (final path in orphans) {
      _owned.remove(path);
      _delete(path);
    }
  }

  /// Discard, a finished upload, or leaving the screen.
  void deleteAll() {
    final all = _owned.toList();
    _owned.clear();
    all.forEach(_delete);
  }
}
