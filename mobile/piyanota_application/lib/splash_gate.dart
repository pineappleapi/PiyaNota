import 'package:flutter/material.dart';

import 'screens/onboarding/widgets/splash_overlay.dart';
import 'services/leaving_app.dart';

/// Plays the splash over whatever is on screen on cold start and on
/// resume, unless the app itself sent the user out (PIYA-201-V2.2).
///
/// It wraps MaterialApp, so it sits above the Navigator as a [Stack] layer
/// rather than a pushed route: the screen beneath keeps its state
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
        appPaused();
        _paused = true;
        _pausedToLeave = isLeavingApp;
      case AppLifecycleState.resumed:
        appResumed();
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

  /// AC2: back while covered must not pop the screen the user returns to.
  /// Works only because this observer is registered before WidgetsApp's
  /// (the binding asks observers in that order), so the gate must stay
  /// above MaterialApp.
  @override
  Future<bool> didPopRoute() async => _showing;

  @override
  Widget build(BuildContext context) {
    // The child stays at index 0 either way, so adding or removing the
    // splash layer never remounts the screen beneath it.
    return Stack(
      alignment: Alignment.topLeft,
      fit: StackFit.expand,
      children: [
        ExcludeSemantics(excluding: _showing, child: widget.child),
        if (_showing)
          // AC4: absorbs taps so the splash cannot be skipped.
          AbsorbPointer(
            // Above MaterialApp there is no MediaQuery or Directionality
            // yet; the overlay needs both.
            child: MediaQuery.fromView(
              view: View.of(context),
              child: Directionality(
                textDirection: TextDirection.ltr,
                child: SplashOverlay(
                  key: ValueKey(_plays),
                  onFinished: () => setState(() => _showing = false),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
