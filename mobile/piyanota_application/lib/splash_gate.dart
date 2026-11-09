import 'package:flutter/material.dart';

import 'screens/onboarding/widgets/splash_overlay.dart';

/// Plays the splash once per cold start (V3 F1). A paused-then-resumed app
/// (camera, gallery, PDF picker, Gmail, home button) shows no splash; process
/// death in the background is a cold start and replays it, which is accepted.
///
/// It wraps MaterialApp, so it sits above the Navigator as a [Stack] layer
/// rather than a pushed route: the screen beneath keeps its state while
/// covered (AC2).
class SplashGate extends StatefulWidget {
  const SplashGate({super.key, required this.child});

  final Widget child;

  @override
  State<SplashGate> createState() => _SplashGateState();
}

class _SplashGateState extends State<SplashGate> with WidgetsBindingObserver {
  // AC1: a cold start mounts the gate, so it starts showing.
  bool _showing = true;

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
                  onFinished: () => setState(() => _showing = false),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
