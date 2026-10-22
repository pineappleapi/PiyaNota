import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/auth_session.dart';
import 'auth_providers.dart';
import 'export_jobs.dart';
import 'export_providers.dart';
import 'processing_providers.dart';
import 'work_owner.dart';

/// Every way into or out of a session goes through these two, so jobs
/// followed for one account are never polled with the next account's
/// token, or shown to it. The processing tracker outlives screens, so
/// clearing it can't be left to whichever screen noticed the 401. The
/// same goes for exports (H1): a running one is stopped, its foreground
/// service and notifications removed, and the history forgotten; and for
/// the scans' own background service and notifications (PIYA-218).
///
/// Reads every provider before returning, so callers may call it after an
/// await as long as [ref] is still usable then.
void _forgetAccountWork(WidgetRef ref) {
  ref.read(processingJobsProvider.notifier).forgetAll();
  ref.read(exportJobsProvider.notifier).cancelAndForgetAll();
  // Never awaited and never throws: logging out can't wait on, or fail
  // because of, the native side.
  unawaited(ref.read(exportServiceProvider).stopAll());
  // PIYA-218: the background service and every conversion notification.
  unawaited(ref.read(scanTrackingServiceProvider).stopAll());
}

/// Wipes the local session after the server rejected it, or on logout,
/// before routing to Login. Everything kept for the account goes too.
/// Never throws: the token is already dead server-side, and a failed
/// local wipe must not trap the user on the screen.
Future<void> endLocalSession(WidgetRef ref) async {
  ref.read(signedInProvider.notifier).set(false);
  _forgetAccountWork(ref);
  final owners = ref.read(workOwnerStoreProvider);
  final storage = ref.read(sessionStorageProvider);
  await owners.clear();
  try {
    await storage.clear();
  } catch (e) {
    debugPrint('Session clear failed: $e');
  }
}

/// Stores a freshly issued session. Work kept on the device (stored scans,
/// a background export) is kept when it is this account's, which is the
/// normal case: every cold start comes through Login (no auto-login,
/// PIYA-214). It is dropped first when another account owned it, or when
/// the owner is unknown. Only then is the session marked signed in, which
/// lets the tracker restore and poll. Rethrows storage failures for the
/// caller's own error message.
Future<void> startSession(WidgetRef ref, AuthSession session) async {
  final owners = ref.read(workOwnerStoreProvider);
  final storage = ref.read(sessionStorageProvider);
  final signedIn = ref.read(signedInProvider.notifier);
  final owner = await owners.load();
  if (owner != session.userId) {
    _forgetAccountWork(ref);
  }
  await storage.save(session);
  await owners.save(session.userId);
  signedIn.set(true);
}
