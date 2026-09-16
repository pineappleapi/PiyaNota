import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';

/// Splash / logo-reveal sequence treated as PIYA-201's step 0 (per user
/// decision — the Figma splash frames feed directly into the swipeable
/// guide rather than gating it behind a separate screen): blank gradient →
/// app icon fades in → wordmark fades in, then hands off to the guide.
class OnboardingSplash extends StatefulWidget {
  const OnboardingSplash({super.key, required this.onFinished});

  final VoidCallback onFinished;

  @override
  State<OnboardingSplash> createState() => _OnboardingSplashState();
}

class _OnboardingSplashState extends State<OnboardingSplash>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _iconOpacity;
  late final Animation<double> _wordmarkOpacity;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1800),
    );

    _iconOpacity = CurvedAnimation(
      parent: _controller,
      curve: const Interval(0.15, 0.55, curve: Curves.easeIn),
    );
    _wordmarkOpacity = CurvedAnimation(
      parent: _controller,
      curve: const Interval(0.55, 0.9, curve: Curves.easeIn),
    );

    _controller.forward();
    _controller.addStatusListener((status) {
      if (status == AnimationStatus.completed) {
        Future.delayed(const Duration(milliseconds: 400), widget.onFinished);
      }
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(gradient: AppTheme.primaryGradient),
      child: Center(
        child: AnimatedBuilder(
          animation: _controller,
          builder: (context, _) {
            return Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Opacity(
                  opacity: _iconOpacity.value,
                  child: Image.asset(
                    'assets/branding/Piyanota_App_Logo.png',
                    width: 96,
                    height: 96,
                  ),
                ),
                const SizedBox(height: 16),
                Opacity(
                  opacity: _wordmarkOpacity.value,
                  child: Image.asset(
                    'assets/branding/Piyanota_FullText_Logo.png',
                    width: 200,
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}
