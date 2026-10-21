import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/auth_session.dart';
import 'auth_providers.dart';
import 'export_jobs.dart';
import 'export_providers.dart';
import 'processing_providers.dart';

/// Every way into or out of a session goes through these two, so jobs
/// followed for one account are never polled with the next account's
/// token, or shown to it. The processing tracker outlives screens, so
/// clearing it can't be left to whichever screen noticed the 401. The
/// same goes for exports (H1): a running one is stopped, its foreground
/// service and notifications removed, and the history forgotten.
void _forgetAccountWork(WidgetRef ref) {
  ref.read(processingJobsProvider.notifier).forgetAll();
  ref.read(exportJobsProvider.notifier).cancelAndForgetAll();
  // Never awaited and never throws: logging out can't wait on, or fail
  // because of, the native side.
  unawaited(ref.read(exportServiceProvider).stopAll());
}

/// Wipes the local session after the server rejected it, before routing
/// to Login. Never throws: the token is already dead server-side, and a
/// failed local wipe must not trap the user on the screen.
Future<void> endLocalSession(WidgetRef ref) async {
  _forgetAccountWork(ref);
  try {
    await ref.read(sessionStorageProvider).clear();
  } catch (e) {
    debugPrint('Session clear failed: $e');
  }
}

/// Stores a freshly issued session. Drops anything still followed first,
/// in case some path reached Login without [endLocalSession]. Rethrows
/// storage failures for the caller's own error message.
Future<void> startSession(WidgetRef ref, AuthSession session) async {
  _forgetAccountWork(ref);
  await ref.read(sessionStorageProvider).save(session);
}
