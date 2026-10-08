import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'routes/app_routes.dart';
import 'screens/auth/login_screen.dart';
import 'screens/auth/password_reset_screen.dart';
import 'screens/auth/sign_up_screen.dart';
import 'screens/capture/capture_screen.dart';
import 'screens/capture/score_details_screen.dart';
import 'screens/library/score_library_screen.dart';
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
        AppRoutes.login: (context) {
          final arguments = ModalRoute.of(context)?.settings.arguments;
          return LoginScreen(
            passwordReset: arguments is PasswordResetSucceeded
                ? arguments
                : null,
          );
        },
        AppRoutes.signUp: (_) => const SignUpScreen(),
        AppRoutes.passwordReset: (_) => const PasswordResetScreen(),
        AppRoutes.scoreLibrary: (_) => const ScoreLibraryScreen(),
        // Playback and Settings land in later PIYA-2xx tickets; the
        // placeholders keep the library's navigation testable now.
        AppRoutes.playback: (context) {
          final arguments = ModalRoute.of(context)?.settings.arguments;
          return ComingSoonScreen(
            title: 'Playback',
            detail: arguments is PlaybackArguments
                ? '${arguments.title} (score #${arguments.scoreId})'
                : null,
          );
        },
        AppRoutes.capture: (_) => const ScoreDetailsScreen(),
        AppRoutes.capturePages: (context) {
          final arguments = ModalRoute.of(context)?.settings.arguments;
          if (arguments is! CapturePagesArguments) {
            // Only reachable through Details, which always passes these.
            return const ScoreDetailsScreen();
          }
          return CaptureScreen(details: arguments.details);
        },
        // Processing (PIYA-207) replaces this placeholder; the job id is
        // what it will poll.
        AppRoutes.processing: (context) {
          final arguments = ModalRoute.of(context)?.settings.arguments;
          return ComingSoonScreen(
            title: 'Processing',
            detail: arguments is ProcessingArguments
                ? '${arguments.title} (job ${arguments.jobId})'
                : null,
          );
        },
        AppRoutes.settings: (_) => const ComingSoonScreen(title: 'Settings'),
      },
    );
  }
}

/// Decides, on cold start, whether to show onboarding (PIYA-201 AC1) or go
/// straight to Login. Onboarding itself is not a named route since it's a
/// one-time gate, not something re-navigated to later.
///
/// Skipping Login when a stored session token is still valid belongs to
/// Auth Flow Integration (PIYA-214), not here.
class _AppEntryPoint extends ConsumerWidget {
  const _AppEntryPoint();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final onboardingCompleted = ref.watch(onboardingCompletedProvider);

    return onboardingCompleted.when(
      data: (completed) =>
          completed ? const LoginScreen() : const OnboardingFlowScreen(),
      loading: () => const Scaffold(backgroundColor: Colors.white),
      error: (_, _) => const OnboardingFlowScreen(),
    );
  }
}
