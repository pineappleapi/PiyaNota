import 'dart:async';

import 'package:flutter/foundation.dart' show visibleForTesting;

/// How long a launch that returned before the app paused still counts as
/// leaving. Some launches (`openAppSettings`, Open folder) finish their
/// future at `startActivity`, before Android reports `paused`; that comes
/// well inside this window. If no pause comes at all (nothing opened), the
/// launch stops counting so a later real background replays the splash.
const leaveAppGrace = Duration(seconds: 3);

/// How many [withoutSplash] calls are still out of the app. A counter, not
/// a flag, so overlapping calls (a permission request, then the picker it
/// guards) each keep the gate quiet until the last one returns.
int _leavingCount = 0;

/// Counts `paused` events, so a call can tell whether the app paused
/// while it ran (a picker) or not yet (a fire-and-forget launch).
int _pauses = 0;

/// Set when a fire-and-forget launch returned before the app paused.
Timer? _launchGrace;

/// Whether the app itself has sent the user out, so `SplashGate` must not
/// replay the splash on the way back (PIYA-201-V2.2 AC3).
bool get isLeavingApp => _leavingCount > 0 || (_launchGrace?.isActive ?? false);

/// `SplashGate` reports each `paused`.
void appPaused() => _pauses++;

/// `SplashGate` reports each `resumed`: any launch has now come back.
void appResumed() {
  _launchGrace?.cancel();
  _launchGrace = null;
}

/// Wrap any call that leaves the app on purpose (picker, folder chooser,
/// permission dialog, Android Settings, another app) so the return does
/// not replay the splash (PIYA-201-V2.2 AC3).
///
/// Only a call that returns `true` (a launcher such as `openAppSettings`
/// reporting that it opened something) keeps counting after it returns;
/// `false` means nothing opened. Pickers and permission requests return
/// other values and only count while their future runs, which covers them:
/// they finish after the user comes back.
///
/// The in-app camera preview is not leaving the app, so `takePicture` is
/// not wrapped.
Future<T> withoutSplash<T>(Future<T> Function() leave) async {
  final pausesBefore = _pauses;
  _leavingCount++;
  try {
    final result = await leave();
    if (result == true && _pauses == pausesBefore) {
      _launchGrace?.cancel();
      _launchGrace = Timer(leaveAppGrace, () {});
    }
    return result;
  } finally {
    _leavingCount--;
  }
}

/// Clears the module state, which outlives a single widget test.
@visibleForTesting
void resetLeavingApp() {
  _leavingCount = 0;
  _pauses = 0;
  appResumed();
}
