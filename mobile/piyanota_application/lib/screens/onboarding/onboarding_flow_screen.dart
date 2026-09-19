import 'dart:ui' show lerpDouble;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../routes/app_routes.dart';
import '../../state/onboarding_providers.dart';
import '../../theme/app_theme.dart';
import 'steps/purpose_step.dart';
import 'steps/voice_selection_step.dart';
import 'steps/workflow_step.dart';
import 'widgets/primary_pill_button.dart';
import 'widgets/progress_dots.dart';

const _stepCount = 3;

// Intro sequence (logo reveal -> header) timing, phased as fractions of
// _introController's 0.0-1.0 range. Eyeballed against the reference capture
// (mobile/piyanota_application/references/PiyaNota-Screens.mp4, 0:00-0:04) —
// no Figma frame exists for this sequence, so these are tunable, not pinned.
const _introDuration = Duration(milliseconds: 3000);
const _iconFadeInterval = Interval(0.0, 0.22, curve: Curves.easeIn);
const _joinInterval = Interval(0.22, 0.48, curve: Curves.easeOut);
const _toHeaderInterval = Interval(0.62, 1.0, curve: Curves.easeInOut);
const _bodyFadeInterval = Interval(0.75, 1.0, curve: Curves.easeIn);

// Lockup geometry at full (pre-header-shrink) size. The icon asset's canvas
// is square, so width == height at any scale. The text asset's canvas is
// 2000x596, so its width is derived from height via that aspect ratio.
const _splashIconSize = 88.0;
const _splashTextHeight = 54.0;
const _splashTextAspect = 2000 / 596;
const _lockupGap = 8.0;
const _textSlideInOffset = 40.0;

// Header (post-shrink, resting) geometry.
const _headerIconSize = 28.0;
const _headerTopPadding = 12.0;
const _headerHeight = _headerTopPadding * 2 + _headerIconSize;
const _headerScale = _headerIconSize / _splashIconSize;

/// Orchestrates PIYA-201: a single continuous intro (icon fade-in -> joins
/// wordmark text -> shrinks into a persistent header) followed by the
/// 3-step swipeable guide (purpose -> workflow -> voice selection) ->
/// Login (Skip) or Sign-Up (Get Started, final step only).
///
/// The intro used to be a separate `OnboardingSplash` screen that got
/// swapped out entirely once finished. Per the reference capture, the logo
/// instead morphs into this screen's header rather than cross-fading away,
/// so the whole sequence now lives in one controller/build here.
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
    final screenCenter = Offset(size.width / 2, size.height / 2);
    final headerCenter = Offset(
      size.width / 2,
      topInset + _headerTopPadding + _headerIconSize / 2,
    );

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppTheme.primaryGradient),
        child: Stack(
          children: [
            SafeArea(
              child: AnimatedBuilder(
                animation: _introController,
                builder: (context, child) {
                  final bodyOpacity = _bodyFadeInterval.transform(
                    _introController.value,
                  );
                  return IgnorePointer(
                    ignoring: bodyOpacity < 1.0,
                    child: Opacity(opacity: bodyOpacity, child: child),
                  );
                },
                child: Column(
                  children: [
                    // Reserved space the animated logo settles into — keeps
                    // this layout stable once the intro finishes.
                    const SizedBox(height: _headerHeight),
                    Align(
                      alignment: Alignment.topRight,
                      child: Padding(
                        padding: const EdgeInsets.only(right: 8, top: 4),
                        child: TextButton(
                          onPressed: _skip,
                          style: TextButton.styleFrom(
                            foregroundColor: Colors.white,
                          ),
                          child: const Text('Skip'),
                        ),
                      ),
                    ),
                    Expanded(
                      child: PageView(
                        controller: _pageController,
                        onPageChanged: (index) =>
                            setState(() => _currentPage = index),
                        children: const [
                          PurposeStep(),
                          WorkflowStep(),
                          VoiceSelectionStep(),
                        ],
                      ),
                    ),
                    ProgressDots(
                      stepCount: _stepCount,
                      currentStep: _currentPage,
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(32, 24, 32, 16),
                      child: SizedBox(
                        width: double.infinity,
                        child: PrimaryPillButton(
                          label: isLastStep ? 'Get Started' : 'Next',
                          backgroundColor: Colors.white,
                          foregroundColor: AppTheme.primaryBlue,
                          onPressed: _next,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            AnimatedBuilder(
              animation: _introController,
              builder: (context, _) {
                final t = _introController.value;
                final iconFadeT = _iconFadeInterval.transform(t);
                final joinT = _joinInterval.transform(t);
                final headerT = _toHeaderInterval.transform(t);

                final groupScale = lerpDouble(1.0, _headerScale, headerT)!;
                final groupCenter = Offset.lerp(
                  screenCenter,
                  headerCenter,
                  headerT,
                )!;

                final textWidth = _splashTextHeight * _splashTextAspect;
                final lockupWidth = _splashIconSize + _lockupGap + textWidth;
                final iconLocalX = -(lockupWidth / 2 - _splashIconSize / 2);
                final textLocalX = lockupWidth / 2 - textWidth / 2;

                final iconX = lerpDouble(0, iconLocalX, joinT)!;
                final textX = lerpDouble(
                  textLocalX + _textSlideInOffset,
                  textLocalX,
                  joinT,
                )!;

                final iconEntranceScale = lerpDouble(0.85, 1.0, iconFadeT)!;
                final iconRenderScale = iconEntranceScale * groupScale;
                final textRenderScale = groupScale;

                return Stack(
                  children: [
                    _LogoPiece(
                      asset: 'assets/branding/Piyanota_App_Logo.png',
                      center: groupCenter + Offset(iconX * groupScale, 0),
                      width: _splashIconSize * iconRenderScale,
                      height: _splashIconSize * iconRenderScale,
                      opacity: iconFadeT,
                    ),
                    _LogoPiece(
                      asset: 'assets/branding/Piyanota_iyanota-text_logo.png',
                      center: groupCenter + Offset(textX * groupScale, 0),
                      width: textWidth * textRenderScale,
                      height: _splashTextHeight * textRenderScale,
                      opacity: joinT,
                    ),
                  ],
                );
              },
            ),
          ],
        ),
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
