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

/// Orchestrates PIYA-201: the 3-step swipeable guide (purpose -> workflow
/// -> voice selection) -> Login (Skip) or Sign-Up (Get Started, final step
/// only).
///
/// The logo intro used to play inside this screen; it now lives in
/// `SplashOverlay`, which `SplashGate` plays over every cold start and
/// resume (PIYA-201-V2.2). This screen is already beneath it when it
/// fades, so the intro plays once, not twice (AC5).
class OnboardingFlowScreen extends ConsumerStatefulWidget {
  const OnboardingFlowScreen({super.key});

  @override
  ConsumerState<OnboardingFlowScreen> createState() =>
      _OnboardingFlowScreenState();
}

class _OnboardingFlowScreenState extends ConsumerState<OnboardingFlowScreen> {
  final _pageController = PageController();
  int _currentPage = 0;

  @override
  void dispose() {
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
    return Scaffold(
      body: SafeArea(
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
                onPageChanged: (index) => setState(() => _currentPage = index),
                children: [
                  const PurposeStep(),
                  const WorkflowStep(),
                  const VoiceSelectionStep(),
                ],
              ),
            ),
            ProgressDots(stepCount: _stepCount, currentStep: _currentPage),
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
    );
  }
}
