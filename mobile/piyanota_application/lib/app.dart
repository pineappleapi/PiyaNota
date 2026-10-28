import 'dart:async';

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
import 'screens/scan_status/scan_background_host.dart';
import 'screens/scan_status/scan_toast_host.dart';
import 'screens/scan_status/scan_navigation.dart';
import 'screens/settings/settings_screen.dart';
import 'services/score_library_api.dart';
import 'splash_gate.dart';
import 'state/auth_providers.dart';
import 'state/onboarding_providers.dart';
import 'state/processing_providers.dart';
import 'state/score_library_providers.dart';
import 'state/session_actions.dart';
import 'state/work_owner.dart';
import 'theme/app_theme.dart';

/// Root widget. Route table is populated as PIYA-2xx screens land.
class PiyaNotaApp extends StatefulWidget {
  const PiyaNotaApp({super.key});

  @override
  State<PiyaNotaApp> createState() => _PiyaNotaAppState();
}

class _PiyaNotaAppState extends State<PiyaNotaApp> {
  /// Lets the app-wide scan toast (PIYA-218 AC7) and a tapped scan
  /// notification, which sit above the Navigator, open Processing or
  /// Playback.
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();
  final ScanRouteStack _routes = ScanRouteStack();

  @override
  Widget build(BuildContext context) {
    // SplashGate wraps the whole app: it covers the scan toast too, keeps
    // every route's state under a resume splash, and sees Android back
    // before the Navigator does (PIYA-201-V2.2 AC2).
    return SplashGate(
      child: MaterialApp(
        title: 'PiyaNota',
        theme: AppTheme.light,
        navigatorKey: _navigatorKey,
        navigatorObservers: [_routes],
        builder: (context, child) => ScanBackgroundHost(
          navigatorKey: _navigatorKey,
          child: ScanToastHost(
            navigatorKey: _navigatorKey,
            routes: _routes,
            child: child ?? const SizedBox.shrink(),
          ),
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
      ),
    );
  }
}

/// Decides, on cold start, where the app opens: onboarding on first launch
/// (PIYA-201 AC1), else the Score Library when a stored session is still
/// valid (PIYA-202-V2.2), else Login. Onboarding itself is not a named
/// route since it's a one-time gate, not something re-navigated to later.
///
/// The session check is a secure-storage read, so it resolves behind the
/// cold-start splash; if it ever outlasts it, a blank screen shows, never
/// a Login that would flash away.
class _AppEntryPoint extends ConsumerStatefulWidget {
  const _AppEntryPoint();

  @override
  ConsumerState<_AppEntryPoint> createState() => _AppEntryPointState();
}

class _AppEntryPointState extends ConsumerState<_AppEntryPoint> {
  static const Widget _placeholder = Scaffold(backgroundColor: Colors.white);

  /// Started once onboarding is known to be done; true = signed in.
  Future<bool>? _session;

  Future<bool> _restoreSession() async {
    bool valid;
    try {
      valid = await ref.read(sessionStorageProvider).hasValidSession();
    } catch (e, stack) {
      // Unreadable storage can't prove a session, so treat it as none.
      debugPrint('Session check failed: $e\n$stack');
      valid = false;
    }
    if (!valid || !mounted) return false;
    // Same as a login, minus the new token: the stored scans are this
    // account's (logout and a different login clear them), so the
    // tracker restores and polls them.
    ref.read(signedInProvider.notifier).set(true);
    _watchFirstLibraryLoad();
    // Not awaited: the Library needn't wait on the platform channel.
    unawaited(_takeLaunchJob());
    return true;
  }

  /// AC5: opens the scan whose notification tap started the app. It is
  /// looked up once, after the restore: a job missing then is gone, and a
  /// later scan reusing its id must not open by surprise.
  Future<void> _takeLaunchJob() async {
    final jobId = await ref.read(scanTrackingServiceProvider).takeLaunchJob();
    if (jobId == null || !mounted) return;
    await ref.read(processingJobsProvider.notifier).restored;
    final job = mounted ? ref.read(processingJobsProvider)[jobId] : null;
    if (job == null || !mounted) return;
    unawaited(openScanJob(Navigator.of(context), ref, job));
  }

  /// AC2 (backend note B2): the first PIYA-306 load is the server's check
  /// of the restored token. A 401 there sends the user to Login; any other
  /// failure (offline, AC3) leaves the Library's own error state up.
  void _watchFirstLibraryLoad() {
    late final ProviderSubscription<AsyncValue<Object?>> subscription;
    subscription = ref.listenManual(scoreLibraryProvider, (_, next) {
      if (next.isLoading) return;
      subscription.close();
      if (next.error is SessionExpiredException) unawaited(_toLogin());
    });
  }

  Future<void> _toLogin() async {
    await endLocalSession(ref);
    if (!mounted) return;
    Navigator.of(context)
        .pushNamedAndRemoveUntil(AppRoutes.login, (_) => false);
  }

  @override
  Widget build(BuildContext context) {
    final onboardingCompleted = ref.watch(onboardingCompletedProvider);

    return onboardingCompleted.when(
      data: (completed) {
        if (!completed) return const OnboardingFlowScreen();
        return FutureBuilder<bool>(
          future: _session ??= _restoreSession(),
          // A check that blew up can't prove a session: Login, not a
          // placeholder that never goes away.
          builder: (context, snapshot) => snapshot.hasError
              ? const LoginScreen()
              : switch (snapshot.data) {
                  true => const ScoreLibraryScreen(),
                  false => const LoginScreen(),
                  null => _placeholder,
                },
        );
      },
      loading: () => _placeholder,
      error: (_, _) => const OnboardingFlowScreen(),
    );
  }
}
