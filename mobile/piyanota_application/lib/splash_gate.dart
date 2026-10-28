import 'package:flutter/material.dart';

import 'screens/onboarding/widgets/splash_overlay.dart';

/// How many [withoutSplash] calls are still out of the app. A counter, not
/// a flag, so overlapping calls (a permission request, then the picker it
/// guards) each keep the gate quiet until the last one returns.
int _leavingCount = 0;

/// Wrap any call that leaves the app on purpose (picker, folder chooser,
/// permission dialog, Android Settings, another app) so the return does
/// not replay the splash (PIYA-201-V2.2 AC3).
///
/// The in-app camera preview is not leaving the app, so `takePicture` is
/// not wrapped.
Future<T> withoutSplash<T>(Future<T> Function() leave) async {
  _leavingCount++;
  try {
    return await leave();
  } finally {
    _leavingCount--;
  }
}

/// Plays the splash over whatever is on screen on cold start and on
/// resume, unless the app itself sent the user out (PIYA-201-V2.2).
///
/// It sits in the MaterialApp builder, above the Navigator, as a [Stack]
/// layer rather than a pushed route: the screen beneath keeps its state
/// (typed text, scroll, open sheets, running exports) while covered (AC2).
class SplashGate extends StatefulWidget {
  const SplashGate({super.key, required this.child});

  final Widget child;

  @override
  State<SplashGate> createState() => _SplashGateState();
}

class _SplashGateState extends State<SplashGate> with WidgetsBindingObserver {
  // AC1: a cold start mounts the gate, so it starts showing.
  bool _showing = true;

  /// Bumped per play so a resume during a play restarts the animation.
  int _plays = 0;

  /// Only `resumed` after `paused` replays: permission dialogs and system
  /// sheets usually raise only `inactive`, and must not replay it.
  bool _paused = false;

  /// Decided at `paused`, not at `resumed`: the picker's result can arrive
  /// before or after `resumed`, but it is always still out when paused.
  bool _pausedToLeave = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.paused:
        _paused = true;
        _pausedToLeave = _leavingCount > 0;
      case AppLifecycleState.resumed:
        final replay = _paused && !_pausedToLeave;
        _paused = false;
        _pausedToLeave = false;
        if (replay) {
          setState(() {
            _showing = true;
            _plays++;
          });
        }
      case AppLifecycleState.detached ||
          AppLifecycleState.inactive ||
          AppLifecycleState.hidden:
        break;
    }
  }

  @override
  Widget build(BuildContext context) {
    // The child stays at index 0 either way, so adding or removing the
    // splash layer never remounts the screen beneath it.
    return Stack(
      fit: StackFit.expand,
      children: [
        ExcludeSemantics(excluding: _showing, child: widget.child),
        if (_showing)
          // AC4: absorbs taps so the splash cannot be skipped.
          AbsorbPointer(
            child: SplashOverlay(
              key: ValueKey(_plays),
              onFinished: () => setState(() => _showing = false),
            ),
          ),
      ],
    );
  }
}
