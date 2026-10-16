import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models/score_details.dart';
import 'routes/app_routes.dart';
import 'screens/auth/login_screen.dart';
import 'screens/auth/password_reset_screen.dart';
import 'screens/auth/sign_up_screen.dart';
import 'screens/capture/capture_screen.dart';
import 'screens/capture/score_details_screen.dart';
import 'screens/library/score_library_screen.dart';
import 'screens/onboarding/onboarding_flow_screen.dart';
import 'screens/playback/playback_screen.dart';
import 'screens/processing/processing_screen.dart';
import 'screens/scan_status/scan_toast_host.dart';
import 'screens/settings/settings_screen.dart';
import 'state/onboarding_providers.dart';
import 'theme/app_theme.dart';

/// Root widget. Route table is populated as PIYA-2xx screens land.
class PiyaNotaApp extends StatefulWidget {
  const PiyaNotaApp({super.key});

  @override
  State<PiyaNotaApp> createState() => _PiyaNotaAppState();
}

class _PiyaNotaAppState extends State<PiyaNotaApp> {
  /// Lets the app-wide scan toast (PIYA-218 AC7), which sits above the
  /// Navigator, open Processing or Playback.
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();
  final ScanRouteStack _routes = ScanRouteStack();

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PiyaNota',
      theme: AppTheme.light,
      navigatorKey: _navigatorKey,
      navigatorObservers: [_routes],
      builder: (context, child) => ScanToastHost(
        navigatorKey: _navigatorKey,
        routes: _routes,
        child: child ?? const SizedBox.shrink(),
      ),
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
        AppRoutes.playback: (context) {
          final arguments = ModalRoute.of(context)?.settings.arguments;
          if (arguments is! PlaybackArguments) {
            // Only reachable from the library and Processing, which always
            // pass these.
            return const ScoreLibraryScreen();
          }
          return PlaybackScreen(
            scoreId: arguments.scoreId,
            title: arguments.title,
          );
        },
        AppRoutes.capture: (context) {
          final arguments = ModalRoute.of(context)?.settings.arguments;
          return ScoreDetailsScreen(
            wholeRetake: arguments is WholeRetakeArguments ? arguments : null,
          );
        },
        AppRoutes.capturePages: (context) {
          final arguments = ModalRoute.of(context)?.settings.arguments;
          if (arguments is! CapturePagesArguments) {
            // Only reachable through Details, which always passes these.
            return const ScoreDetailsScreen();
          }
          return CaptureScreen(
            details: arguments.details,
            wholeRetake: arguments.wholeRetake,
          );
        },
        AppRoutes.processing: (context) {
          final arguments = ModalRoute.of(context)?.settings.arguments;
          if (arguments is! ProcessingArguments) {
            // Only reachable from Capture, which always passes these.
            return const ScoreLibraryScreen();
          }
          return ProcessingScreen(
            jobId: arguments.jobId,
            title: arguments.title,
          );
        },
        AppRoutes.captureRetake: (context) {
          final arguments = ModalRoute.of(context)?.settings.arguments;
          if (arguments is! CaptureRetakeArguments) {
            // Only reachable from Processing, which always passes these.
            return const ScoreLibraryScreen();
          }
          return CaptureScreen(
            details: ScoreDetails(title: arguments.title),
            retake: arguments,
          );
        },
        // PIYA-212 AC5: the gate sends an expired session to Login.
        AppRoutes.settings: (_) => const SettingsGate(),
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
