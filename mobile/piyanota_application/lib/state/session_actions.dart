import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/auth_session.dart';
import 'auth_providers.dart';
import 'export_jobs.dart';
import 'export_providers.dart';
import 'playback_providers.dart';
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
/// Reads every provider now and returns the clean-up, so a caller can
/// run it after an await without touching [ref] again (review L1): the
/// screen that owns [ref] may be gone by then.
void Function() _accountWorkForgetter(WidgetRef ref) {
  final scans = ref.read(processingJobsProvider.notifier);
  final exports = ref.read(exportJobsProvider.notifier);
  final exportDevice = ref.read(exportServiceProvider);
  final scanDevice = ref.read(scanTrackingServiceProvider);
  return () {
    scans.forgetAll();
    exports.cancelAndForgetAll();
    // Never awaited and never throws: logging out can't wait on, or fail
    // because of, the native side.
    unawaited(exportDevice.stopAll());
    // PIYA-218: the background service and every conversion notification.
    unawaited(scanDevice.stopAll());
  };
}

/// Wipes the local session after the server rejected it, or on logout,
/// before routing to Login. Never throws: the token is already dead
/// server-side, and a failed local wipe must not trap the user on the
/// screen.
///
/// The offline copy of results (F10) is wiped only when [wipeResults] is
/// set: explicit Log out and Delete account. A session expiry keeps it, and
/// keeps the owner id, so the same account logging back in still has its
/// files and a different one is caught by [startSession].
Future<void> endLocalSession(WidgetRef ref, {bool wipeResults = false}) async {
  ref.read(signedInProvider.notifier).set(false);
  _accountWorkForgetter(ref)();
  final results = ref.read(localResultsStoreProvider);
  final owners = ref.read(workOwnerStoreProvider);
  final storage = ref.read(sessionStorageProvider);
  if (wipeResults) {
    // Results are keyed by score id only, so the next account must not see
    // this one's scores offline. Not awaited and never throws: like the
    // native stops above, logging out must not wait on file IO.
    unawaited(results.deleteAll());
    await owners.clear();
  }
  try {
    await storage.clear();
  } catch (e) {
    debugPrint('Session clear failed: $e');
  }
}

/// Delete account's local half, run only after the server returned 200.
/// [endLocalSession] stops scan polling and the background service, forgets
/// the stored scans and clears secure storage; this adds the login-wait
/// keys and the results folder. Never throws: the account is already gone
/// server-side, so a failed local step must not trap the user.
Future<void> wipeAccountLocalData(WidgetRef ref) async {
  final throttle = ref.read(loginThrottleProvider);
  await endLocalSession(ref, wipeResults: true);
  try {
    await throttle.clearAll();
  } catch (e, stack) {
    debugPrint('Account wipe incomplete: $e\n$stack');
  }
}

/// Stores a freshly issued session. Work kept on the device (stored scans,
/// a background export) is kept when it is this account's, which is the
/// normal case: the same person logging in again after their session
/// expired. It is dropped first when another account owned it, or when
/// the owner is unknown. Only then is the session marked signed in, which
/// lets the tracker restore and poll. Rethrows storage failures for the
/// caller's own error message.
Future<void> startSession(WidgetRef ref, AuthSession session) async {
  final owners = ref.read(workOwnerStoreProvider);
  final storage = ref.read(sessionStorageProvider);
  final signedIn = ref.read(signedInProvider.notifier);
  final forgetAccountWork = _accountWorkForgetter(ref);
  final owner = await owners.load();
  // shortcut: trusts the server never to reuse a user id, so a DB reset or
  // a switch between fake and real builds can inherit another account's
  // work; upgrade by storing the email or API base URL with the owner id.
  if (owner != session.userId) {
    forgetAccountWork();
    // Another account's offline results must not be readable by this one.
    unawaited(ref.read(localResultsStoreProvider).deleteAll());
  }
  await storage.save(session);
  await owners.save(session.userId);
  signedIn.set(true);
}
