import 'dart:ui' show lerpDouble;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../routes/app_routes.dart';
import '../../state/onboarding_providers.dart';
import '../../theme/app_theme.dart';
import 'steps/purpose_step.dart';
import 'steps/voice_selection_step.dart';
import 'steps/workflow_step.dart';
import '../../widgets/primary_pill_button.dart';
import 'widgets/progress_dots.dart';

const _stepCount = 3;

// Intro sequence (icon fade-in -> joins wordmark -> whole splash fades to
// reveal onboarding) timing, phased as fractions of _introController's
// 0.0-1.0 range. Eyeballed — no Figma frame exists for this sequence, so
// these are tunable, not pinned.
const _introDuration = Duration(milliseconds: 4600);
const _iconFadeInterval = Interval(0.1, 0.2, curve: Curves.easeIn);
const _joinInterval = Interval(0.4, 0.8, curve: Curves.easeOut);
const _handoffInterval = Interval(0.8, 1.0, curve: Curves.easeInOut);

// Lockup geometry. The icon fades in at a larger "solo" size, then shrinks
// down to the lockup size as it slides in next to the text. The icon
// asset's canvas is square, so width == height at any scale. The text
// asset's canvas is 2000x596, so its width is derived from height via that
// aspect ratio.
const _soloIconSize = 120.0;
const _splashIconSize = 88.0;
const _splashTextHeight = 50.0;
const _splashTextAspect = 2000 / 596;
const _lockupGap = -20.0;
const _textSlideInOffset = 20.0;

// Vertical anchor for the lockup: "near the top, not dead-center" per the
// reference request, expressed as a fraction of screen height so it scales
// across device sizes; clamped so it never crowds the status bar.
const _logoAnchorFraction = 0.30;

/// Orchestrates PIYA-201: a single continuous intro (icon fade-in -> joins
/// wordmark text -> whole splash layer fades away) followed by the 3-step
/// swipeable guide (purpose -> workflow -> voice selection) -> Login (Skip)
/// or Sign-Up (Get Started, final step only).
///
/// The intro used to be a separate `OnboardingSplash` screen that got
/// swapped out entirely once finished; it now lives in this screen's own
/// controller so the handoff can be a real cross-fade instead of a hard
/// widget swap.
class OnboardingFlowScreen extends ConsumerStatefulWidget {
  const OnboardingFlowScreen({super.key});

  @override
  ConsumerState<OnboardingFlowScreen> createState() =>
      _OnboardingFlowScreenState();
}

class _OnboardingFlowScreenState extends ConsumerState<OnboardingFlowScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _introController;
  final _pageController = PageController();
  int _currentPage = 0;

  @override
  void initState() {
    super.initState();
    _introController = AnimationController(
      vsync: this,
      duration: _introDuration,
    )..forward();
  }

  @override
  void dispose() {
    _introController.dispose();
    _pageController.dispose();
    super.dispose();
  }

  Future<void> _skip() async {
    // AC4: Skip is available on every content step and routes to Login —
    // existing users already have an account and don't need Sign-Up.
    await ref.read(onboardingPrefsServiceProvider).completeOnboarding();
    ref.invalidate(onboardingCompletedProvider);
    if (!mounted) return;
    Navigator.of(context).pushReplacementNamed(AppRoutes.login);
  }

  void _back() {
    _pageController.previousPage(
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOut,
    );
  }

  Future<void> _next() async {
    if (_currentPage < _stepCount - 1) {
      _pageController.nextPage(
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
      );
      return;
    }

    // AC5/AC6: final step — persist the selected voice as default and route
    // to Sign-Up, not Login.
    final selectedVoice = ref.read(selectedVoicePartProvider);
    await ref
        .read(onboardingPrefsServiceProvider)
        .completeOnboarding(defaultVoice: selectedVoice);
    ref.invalidate(onboardingCompletedProvider);
    if (!mounted) return;
    Navigator.of(context).pushReplacementNamed(AppRoutes.signUp);
  }

  @override
  Widget build(BuildContext context) {
    final isLastStep = _currentPage == _stepCount - 1;
    final size = MediaQuery.of(context).size;
    final topInset = MediaQuery.of(context).padding.top;
    final logoAnchorY = (size.height * _logoAnchorFraction).clamp(
      topInset + _soloIconSize / 2 + 8,
      size.height,
    );
    final groupCenter = Offset(size.width / 2, logoAnchorY);

    return Scaffold(
      body: Stack(
        children: [
          // Onboarding content — revealed as the splash layer fades away.
          AnimatedBuilder(
            animation: _introController,
            builder: (context, child) {
              final bodyOpacity = _handoffInterval.transform(
                _introController.value,
              );
              return IgnorePointer(
                ignoring: bodyOpacity < 1.0,
                child: Opacity(opacity: bodyOpacity, child: child),
              );
            },
            child: SafeArea(
              child: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.only(left: 8, top: 4),
                    child: Align(
                      alignment: Alignment.topLeft,
                      child: _currentPage > 0
                          ? IconButton(
                              onPressed: _back,
                              icon: const Icon(Icons.arrow_back),
                            )
                          : const SizedBox(height: 48),
                    ),
                  ),
                  Expanded(
                    child: PageView(
                      controller: _pageController,
                      onPageChanged: (index) =>
                          setState(() => _currentPage = index),
                      children: [
                        const PurposeStep(),
                        const WorkflowStep(),
                        VoiceSelectionStep(onConductorTap: _skip),
                      ],
                    ),
                  ),
                  ProgressDots(
                    stepCount: _stepCount,
                    currentStep: _currentPage,
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(32, 24, 32, 4),
                    child: SizedBox(
                      width: double.infinity,
                      child: PrimaryPillButton(
                        label: isLastStep ? 'Get Started' : 'Next',
                        backgroundColor: AppTheme.onboardingButtonBlue,
                        foregroundColor: Colors.white,
                        onPressed: _next,
                      ),
                    ),
                  ),
                  TextButton(
                    onPressed: _skip,
                    child: Text(
                      'Skip',
                      style: TextStyle(color: AppTheme.onboardingSkipText),
                    ),
                  ),
                ],
              ),
            ),
          ),
          // Splash layer — gradient background + logo lockup, fades out to
          // hand off to the onboarding content beneath it.
          AnimatedBuilder(
            animation: _introController,
            builder: (context, _) {
              final t = _introController.value;
              final iconFadeT = _iconFadeInterval.transform(t);
              final joinT = _joinInterval.transform(t);
              final splashOpacity = 1 - _handoffInterval.transform(t);

              final textWidth = _splashTextHeight * _splashTextAspect;
              final lockupWidth = _splashIconSize + _lockupGap + textWidth;
              final iconLocalX = -(lockupWidth / 2 - _splashIconSize / 2);
              final textLocalX = lockupWidth / 2 - textWidth / 2;

              final iconSize = lerpDouble(
                _soloIconSize,
                _splashIconSize,
                joinT,
              )!;
              final iconEntranceScale = lerpDouble(0.85, 1.0, iconFadeT)!;
              final iconX = lerpDouble(0, iconLocalX, joinT)!;
              final textX = lerpDouble(
                textLocalX + _textSlideInOffset,
                textLocalX,
                joinT,
              )!;

              return IgnorePointer(
                child: Opacity(
                  opacity: splashOpacity,
                  child: Container(
                    decoration: const BoxDecoration(
                      gradient: AppTheme.primaryGradient,
                    ),
                    width: double.infinity,
                    height: double.infinity,
                    child: Stack(
                      children: [
                        _LogoPiece(
                          asset: 'assets/branding/Piyanota_App_Logo.png',
                          center: groupCenter + Offset(iconX, 0),
                          width: iconSize * iconEntranceScale,
                          height: iconSize * iconEntranceScale,
                          opacity: iconFadeT,
                        ),
                        _LogoPiece(
                          asset:
                              'assets/branding/Piyanota_iyanota-text_logo.png',
                          center: groupCenter + Offset(textX, 0),
                          width: textWidth,
                          height: _splashTextHeight,
                          opacity: joinT,
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _LogoPiece extends StatelessWidget {
  const _LogoPiece({
    required this.asset,
    required this.center,
    required this.width,
    required this.height,
    required this.opacity,
  });

  final String asset;
  final Offset center;
  final double width;
  final double height;
  final double opacity;

  @override
  Widget build(BuildContext context) {
    if (opacity <= 0) return const SizedBox.shrink();
    return Positioned(
      left: center.dx - width / 2,
      top: center.dy - height / 2,
      width: width,
      height: height,
      child: Opacity(
        opacity: opacity,
        child: Image.asset(asset, fit: BoxFit.contain),
      ),
    );
  }
}
