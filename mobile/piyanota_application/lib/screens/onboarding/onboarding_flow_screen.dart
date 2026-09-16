import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../routes/app_routes.dart';
import '../../state/onboarding_providers.dart';
import '../../theme/app_theme.dart';
import 'onboarding_splash.dart';
import 'steps/purpose_step.dart';
import 'steps/voice_selection_step.dart';
import 'steps/workflow_step.dart';
import 'widgets/primary_pill_button.dart';
import 'widgets/progress_dots.dart';

const _stepCount = 3;

/// Orchestrates PIYA-201: splash reveal (step 0) → 3-step swipeable guide
/// (purpose → workflow → voice selection) → Login (Skip) or Sign-Up
/// (Get Started, final step only).
class OnboardingFlowScreen extends ConsumerStatefulWidget {
  const OnboardingFlowScreen({super.key});

  @override
  ConsumerState<OnboardingFlowScreen> createState() =>
      _OnboardingFlowScreenState();
}

class _OnboardingFlowScreenState extends ConsumerState<OnboardingFlowScreen> {
  bool _showSplash = true;
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
    if (_showSplash) {
      return OnboardingSplash(
        onFinished: () => setState(() => _showSplash = false),
      );
    }

    final isLastStep = _currentPage == _stepCount - 1;

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppTheme.primaryGradient),
        child: SafeArea(
          child: Column(
            children: [
              Align(
                alignment: Alignment.topRight,
                child: Padding(
                  padding: const EdgeInsets.only(right: 8, top: 4),
                  child: TextButton(
                    onPressed: _skip,
                    style: TextButton.styleFrom(foregroundColor: Colors.white),
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
              ProgressDots(stepCount: _stepCount, currentStep: _currentPage),
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
    );
  }
}
