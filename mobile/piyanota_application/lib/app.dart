import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'routes/app_routes.dart';
import 'screens/onboarding/onboarding_flow_screen.dart';
import 'screens/placeholder/coming_soon_screen.dart';
import 'state/onboarding_providers.dart';
import 'theme/app_theme.dart';

/// Root widget. Route table is populated as PIYA-2xx screens land.
class PiyaNotaApp extends StatelessWidget {
  const PiyaNotaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PiyaNota',
      theme: AppTheme.light,
      home: const _AppEntryPoint(),
      routes: {
        AppRoutes.login: (_) => const ComingSoonScreen(title: 'Login'),
        AppRoutes.signUp: (_) => const ComingSoonScreen(title: 'Sign Up'),
      },
    );
  }
}

/// Decides, on cold start, whether to show onboarding (PIYA-201 AC1) or go
/// straight to Login. Onboarding itself is not a named route since it's a
/// one-time gate, not something re-navigated to later.
class _AppEntryPoint extends ConsumerWidget {
  const _AppEntryPoint();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final onboardingCompleted = ref.watch(onboardingCompletedProvider);

    return onboardingCompleted.when(
      data: (completed) => completed
          ? const ComingSoonScreen(title: 'Login')
          : const OnboardingFlowScreen(),
      loading: () => const Scaffold(backgroundColor: Colors.white),
      error: (_, _) => const OnboardingFlowScreen(),
    );
  }
}
