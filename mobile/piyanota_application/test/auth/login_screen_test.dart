import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/models/auth_session.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/auth/auth_messages.dart';
import 'package:piyanota_application/screens/auth/login_screen.dart';
import 'package:piyanota_application/screens/auth/sign_up_screen.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/login_throttle.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/state/auth_providers.dart';

import 'package:piyanota_application/state/processing_providers.dart';

import '../processing/processing_fakes.dart'
    show ScriptedProcessingApi, expectTrackerCleared, running, seedOldJob;
import 'auth_test_harness.dart';

const _logIn = 'Log In';
const _email = 'maria@example.com';
const _password = 'secret123';

Finder get _emailField => find.byType(TextFormField).at(0);
Finder get _passwordField => find.byType(TextFormField).at(1);

Future<void> _fillAndSubmit(WidgetTester tester) async {
  await tester.enterText(_emailField, _email);
  await tester.enterText(_passwordField, _password);
  await tester.pump();
  await tester.tap(buttonLabelled(_logIn));
  await tester.pump();
}

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    // The work owner (review H1) lives in SharedPreferences.
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('a new login drops jobs followed for the last account', (
    tester,
  ) async {
    final processing = ScriptedProcessingApi([running(10)]);
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(),
      api: ScriptedAuthApi(onLogin: () async => testSession()),
      extraOverrides: [processingApiProvider.overrideWithValue(processing)],
    );
    await seedOldJob(tester, processing);

    await _fillAndSubmit(tester);
    await tester.pumpAndSettle();
    expect(find.text(libraryMarker), findsOneWidget);
    await expectTrackerCleared(tester, processing);
  });

  testWidgets('AC1: Log In disabled until email and password both non-empty', (
    tester,
  ) async {
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(),
      api: ScriptedAuthApi(),
    );

    expect(isButtonEnabled(tester, _logIn), isFalse);
    await tester.enterText(_emailField, _email);
    await tester.pump();
    expect(isButtonEnabled(tester, _logIn), isFalse);
    await tester.enterText(_passwordField, _password);
    await tester.pump();
    expect(isButtonEnabled(tester, _logIn), isTrue);
    await tester.enterText(_emailField, '   ');
    await tester.pump();
    expect(isButtonEnabled(tester, _logIn), isFalse);
  });

  group('PIYA-202-V2.1 wait after a wrong login', () {
    var now = DateTime.utc(2026, 10, 28, 9);
    late LoginThrottle throttle;

    setUp(() {
      now = DateTime.utc(2026, 10, 28, 9);
      throttle = LoginThrottle(clock: () => now);
    });

    /// Wrong password whose 401 starts a wait of [seconds], as wrong 5 does.
    ScriptedAuthApi wrongPassword({int seconds = 30}) => ScriptedAuthApi(
      onLogin: () async =>
          throw InvalidCredentialsException(retryAfterSeconds: seconds),
    );

    Future<void> pumpLogin(WidgetTester tester, ScriptedAuthApi api) =>
        pumpAuthScreen(
          tester,
          screen: const LoginScreen(),
          api: api,
          extraOverrides: [loginThrottleProvider.overrideWithValue(throttle)],
        );

    /// Moves the injected clock and the test clock together.
    Future<void> elapse(WidgetTester tester, Duration d) async {
      now = now.add(d);
      await tester.pump(d);
    }

    Future<void> resubmit(WidgetTester tester) async {
      await tester.tap(buttonLabelled(_logIn));
      await tester.pump();
      await tester.pump();
    }

    testWidgets('AC1: 1st wrong password shows 0:30 and disables Log In', (
      tester,
    ) async {
      await pumpLogin(tester, wrongPassword());
      await _fillAndSubmit(tester);
      await tester.pump();

      expect(find.text('Try again in 0:30'), findsOneWidget);
      expect(find.text(AuthMessages.incorrectCredentials), findsOneWidget);
      expect(isButtonEnabled(tester, _logIn), isFalse);
    });

    testWidgets('AC1: countdown ticks down and re-enables at 0', (
      tester,
    ) async {
      await pumpLogin(tester, wrongPassword());
      await _fillAndSubmit(tester);
      await tester.pump();

      await elapse(tester, const Duration(seconds: 1));
      expect(find.text('Try again in 0:29'), findsOneWidget);
      await elapse(tester, const Duration(seconds: 28));
      expect(find.text('Try again in 0:01'), findsOneWidget);
      expect(isButtonEnabled(tester, _logIn), isFalse);
      await elapse(tester, const Duration(seconds: 1));
      expect(find.textContaining('Try again in'), findsNothing);
      expect(isButtonEnabled(tester, _logIn), isTrue);
    });

    testWidgets('a stale countdown catches up after a long pause', (
      tester,
    ) async {
      await pumpLogin(tester, wrongPassword());
      await _fillAndSubmit(tester);
      await tester.pump();

      // App was backgrounded: the clock moved 20 s but only one tick fired.
      now = now.add(const Duration(seconds: 20));
      await tester.pump(const Duration(seconds: 1));
      expect(find.text('Try again in 0:10'), findsOneWidget);
    });

    testWidgets('AC2: the next 401 wait is the server value, 1:00', (
      tester,
    ) async {
      var seconds = 30;
      final api = ScriptedAuthApi(
        onLogin: () async =>
            throw InvalidCredentialsException(retryAfterSeconds: seconds),
      );
      await pumpLogin(tester, api);
      await _fillAndSubmit(tester);
      await elapse(tester, const Duration(seconds: 30));
      seconds = 60;
      await resubmit(tester);

      expect(find.text('Try again in 1:00'), findsOneWidget);
    });

    testWidgets('a 3600 s lock reads 1:00:00 and ticks without wrapping', (
      tester,
    ) async {
      await pumpLogin(tester, wrongPassword(seconds: 3600));
      await _fillAndSubmit(tester);
      await tester.pump();
      expect(find.text('Try again in 1:00:00'), findsOneWidget);

      await elapse(tester, const Duration(seconds: 1));
      expect(find.text('Try again in 59:59'), findsOneWidget);
      expect(isButtonEnabled(tester, _logIn), isFalse);
    });

    testWidgets('wrongs 1 to 4 keep Log In enabled; only 1 left is hinted', (
      tester,
    ) async {
      var left = 4;
      final api = ScriptedAuthApi(
        onLogin: () async =>
            throw InvalidCredentialsException(attemptsRemaining: left),
      );
      await pumpLogin(tester, api);
      await _fillAndSubmit(tester);
      await tester.pump();
      expect(find.text(AuthMessages.incorrectCredentials), findsOneWidget);
      expect(find.text(AuthMessages.oneTryLeft), findsNothing);
      expect(find.textContaining('Try again in'), findsNothing);
      expect(isButtonEnabled(tester, _logIn), isTrue);

      left = 2;
      await resubmit(tester);
      expect(find.text(AuthMessages.oneTryLeft), findsNothing);

      left = 1;
      await resubmit(tester);
      expect(find.text(AuthMessages.incorrectCredentials), findsOneWidget);
      expect(find.text(AuthMessages.oneTryLeft), findsOneWidget);
      expect(isButtonEnabled(tester, _logIn), isTrue);
    });

    testWidgets('the wait leaves Forgot Password? active', (tester) async {
      await pumpLogin(tester, wrongPassword());
      await _fillAndSubmit(tester);
      await tester.pump();

      expect(isButtonEnabled(tester, _logIn), isFalse);
      final forgot = tester.widget<TextButton>(
        find.widgetWithText(TextButton, 'Forgot Password?'),
      );
      expect(forgot.onPressed, isNotNull);
    });

    testWidgets('a saved wait clears a shown error and hint', (tester) async {
      final api = ScriptedAuthApi(
        onLogin: () async =>
            throw const InvalidCredentialsException(attemptsRemaining: 1),
      );
      await pumpLogin(tester, api);
      await _fillAndSubmit(tester);
      await tester.pump();
      expect(find.text(AuthMessages.oneTryLeft), findsOneWidget);

      await throttle.recordServerWait(
        'other@example.com',
        const Duration(seconds: 30),
      );
      await tester.enterText(_emailField, 'other@example.com');
      await tester.pump();
      await tester.pump();
      expect(find.textContaining('Try again in'), findsOneWidget);
      expect(find.text(AuthMessages.incorrectCredentials), findsNothing);
      expect(find.text(AuthMessages.oneTryLeft), findsNothing);
    });

    testWidgets('a 429 without seconds starts no wait and counts nothing', (
      tester,
    ) async {
      final api = ScriptedAuthApi(
        onLogin: () async => throw const AuthRateLimitedException(),
      );
      await pumpLogin(tester, api);
      await _fillAndSubmit(tester);
      await tester.pump();

      expect(find.text(AuthMessages.tooManyAttempts), findsOneWidget);
      expect(find.textContaining('Try again in'), findsNothing);
      expect(await throttle.remaining(_email), Duration.zero);
    });

    testWidgets('AC3: a success resets the count', (tester) async {
      var succeed = false;
      final api = ScriptedAuthApi(
        onLogin: () async => succeed
            ? testSession()
            : throw const InvalidCredentialsException(retryAfterSeconds: 30),
      );
      await pumpLogin(tester, api);
      await _fillAndSubmit(tester);
      await elapse(tester, const Duration(seconds: 30));
      succeed = true;
      await resubmit(tester);
      await tester.pumpAndSettle();
      expect(find.text(libraryMarker), findsOneWidget);

      expect(await throttle.remaining(_email), Duration.zero);
    });

    testWidgets('AC5: server retryAfterSeconds 90 shows 1:30', (tester) async {
      final api = ScriptedAuthApi(
        onLogin: () async =>
            throw const AuthRateLimitedException(retryAfterSeconds: 90),
      );
      await pumpLogin(tester, api);
      await _fillAndSubmit(tester);
      await tester.pump();

      expect(find.text('Try again in 1:30'), findsOneWidget);
      expect(isButtonEnabled(tester, _logIn), isFalse);
    });

    testWidgets('AC6: a network failure adds nothing to the count', (
      tester,
    ) async {
      final api = ScriptedAuthApi(
        onLogin: () async => throw const AuthNetworkException(),
      );
      await pumpLogin(tester, api);
      await _fillAndSubmit(tester);
      await tester.pump();

      expect(find.textContaining('Try again in'), findsNothing);
      expect(isButtonEnabled(tester, _logIn), isTrue);
      expect(await throttle.remaining(_email), Duration.zero);
    });

    testWidgets('AC4: a different email is not blocked', (tester) async {
      await pumpLogin(tester, wrongPassword());
      await _fillAndSubmit(tester);
      await tester.pump();
      expect(isButtonEnabled(tester, _logIn), isFalse);

      await tester.enterText(_emailField, 'other@example.com');
      await tester.pump();
      await tester.pump();
      expect(find.textContaining('Try again in'), findsNothing);
      expect(isButtonEnabled(tester, _logIn), isTrue);
    });

    testWidgets('AC4: a saved wait survives reopening the screen', (
      tester,
    ) async {
      await throttle.recordServerWait(_email, const Duration(seconds: 30));
      await elapse(tester, const Duration(seconds: 5));
      await pumpLogin(tester, wrongPassword());
      await tester.enterText(_emailField, _email);
      await tester.enterText(_passwordField, _password);
      await tester.pump();
      await tester.pump();

      expect(find.text('Try again in 0:25'), findsOneWidget);
      expect(isButtonEnabled(tester, _logIn), isFalse);
    });

    testWidgets('a differently-cased email hits the same wait', (tester) async {
      await throttle.recordServerWait(_email, const Duration(seconds: 30));
      await pumpLogin(tester, wrongPassword());
      await tester.enterText(_emailField, 'MARIA@Example.com');
      await tester.enterText(_passwordField, _password);
      await tester.pump();
      await tester.pump();

      expect(find.text('Try again in 0:30'), findsOneWidget);
    });

    test('the stored wait clears at expiry', () async {
      await throttle.recordServerWait(_email, const Duration(seconds: 30));
      now = now.add(const Duration(seconds: 29));
      expect(await throttle.remaining(_email), const Duration(seconds: 1));
      now = now.add(const Duration(seconds: 1));
      expect(await throttle.remaining(_email), Duration.zero);
    });

    testWidgets('the spoken countdown stays current and is announced twice', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await pumpLogin(tester, wrongPassword());
      await _fillAndSubmit(tester);
      await tester.pump();

      expect(
        tester.takeAnnouncements(),
        contains(isAccessibilityAnnouncement('Try again in 0:30')),
      );
      await elapse(tester, const Duration(seconds: 18));
      // A focused read is current, and ticks are not announced.
      expect(find.bySemanticsLabel('Try again in 0:12'), findsOneWidget);
      expect(find.bySemanticsLabel('Try again in 0:30'), findsNothing);
      expect(tester.takeAnnouncements(), isEmpty);

      await elapse(tester, const Duration(seconds: 12));
      expect(
        tester.takeAnnouncements(),
        contains(isAccessibilityAnnouncement(AuthMessages.canTryAgain)),
      );
      // No stray node is left behind after the wait.
      expect(find.bySemanticsLabel(RegExp('Try again')), findsNothing);
      expect(find.bySemanticsLabel(AuthMessages.canTryAgain), findsNothing);
      handle.dispose();
    });

    testWidgets('a 429 with no error banner is still announced', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      final api = ScriptedAuthApi(
        onLogin: () async =>
            throw const AuthRateLimitedException(retryAfterSeconds: 90),
      );
      await pumpLogin(tester, api);
      await _fillAndSubmit(tester);
      await tester.pump();

      expect(
        tester.takeAnnouncements(),
        contains(isAccessibilityAnnouncement('Try again in 1:30')),
      );
      handle.dispose();
    });
  });

  testWidgets('AC2: invalid credentials show inline error, email kept', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onLogin: () async => throw const InvalidCredentialsException(),
    );
    await pumpAuthScreen(tester, screen: const LoginScreen(), api: api);

    await _fillAndSubmit(tester);
    await tester.pumpAndSettle();

    expect(find.text(AuthMessages.incorrectCredentials), findsOneWidget);
    expect(find.text(AuthMessages.network), findsNothing);
    expect(find.widgetWithText(TextFormField, _email), findsOneWidget);
    expect(find.text(libraryMarker), findsNothing);
  });

  testWidgets('AC3: success stores token securely and routes to library', (
    tester,
  ) async {
    final api = ScriptedAuthApi(onLogin: () async => testSession());
    await pumpAuthScreen(tester, screen: const LoginScreen(), api: api);

    await _fillAndSubmit(tester);
    await tester.pumpAndSettle();

    expect(api.loginCalls, 1);
    expect(api.lastEmail, _email);
    expect(
      await const FlutterSecureStorage().read(key: 'session_token'),
      'sess_a1b2c3d4',
    );
    expect(find.text(libraryMarker), findsOneWidget);
  });

  testWidgets('AC4: Forgot Password? routes to Password Reset', (tester) async {
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(),
      api: ScriptedAuthApi(),
    );

    await tester.tap(find.text('Forgot Password?'));
    await tester.pumpAndSettle();

    expect(find.text(passwordResetMarker), findsOneWidget);
  });

  testWidgets('AC5: Sign Up link routes to Sign-Up', (tester) async {
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(),
      api: ScriptedAuthApi(),
      stubSignUp: true,
    );

    expect(find.text("Don't have an account?"), findsOneWidget);
    await tester.tap(find.widgetWithText(TextButton, 'Sign Up'));
    await tester.pumpAndSettle();

    expect(find.text(signUpMarker), findsOneWidget);
  });

  testWidgets('AC6: loading state shown and repeat submission blocked', (
    tester,
  ) async {
    final pending = Completer<AuthSession>();
    final api = ScriptedAuthApi(onLogin: () => pending.future);
    await pumpAuthScreen(tester, screen: const LoginScreen(), api: api);

    await _fillAndSubmit(tester);

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(
      tester.widget<ElevatedButton>(find.byType(ElevatedButton)).onPressed,
      isNull,
    );
    await tester.tap(find.byType(ElevatedButton));
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump();
    expect(api.loginCalls, 1);

    pending.complete(testSession());
    await tester.pumpAndSettle();
    expect(find.text(libraryMarker), findsOneWidget);
  });

  testWidgets('AC7: network failure shows a distinct connectivity error', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onLogin: () async => throw const AuthNetworkException(),
    );
    await pumpAuthScreen(tester, screen: const LoginScreen(), api: api);

    await _fillAndSubmit(tester);
    await tester.pumpAndSettle();

    expect(find.text(AuthMessages.network), findsOneWidget);
    expect(find.text(AuthMessages.incorrectCredentials), findsNothing);
    // Recoverable: the user can retry once back online.
    expect(isButtonEnabled(tester, _logIn), isTrue);
  });

  testWidgets('unexpected error releases loading state', (tester) async {
    final api = ScriptedAuthApi(
      onLogin: () async => throw StateError('misconfigured'),
    );
    await pumpAuthScreen(tester, screen: const LoginScreen(), api: api);

    await _fillAndSubmit(tester);
    await tester.pumpAndSettle();

    expect(find.text(AuthMessages.serverError), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(isButtonEnabled(tester, _logIn), isTrue);
  });

  testWidgets('secure-storage failure blocks entry with a distinct error', (
    tester,
  ) async {
    final backing = FaultySecureStorage()..failWritesFor.add('session_token');
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(),
      api: ScriptedAuthApi(onLogin: () async => testSession()),
      storage: SessionStorage(backing),
    );

    await _fillAndSubmit(tester);
    await tester.pumpAndSettle();

    expect(find.text(AuthMessages.sessionSaveFailed), findsOneWidget);
    expect(find.text(libraryMarker), findsNothing);
    expect(backing.values, isEmpty);
  });

  testWidgets('back from Sign-Up returns to Login instead of exiting', (
    tester,
  ) async {
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(),
      api: ScriptedAuthApi(),
      extraRoutes: {AppRoutes.signUp: (_) => const SignUpScreen()},
    );

    await tester.tap(find.widgetWithText(TextButton, 'Sign Up'));
    await tester.pumpAndSettle();
    expect(find.byType(SignUpScreen), findsOneWidget);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.byType(SignUpScreen), findsNothing);
    expect(find.byType(LoginScreen), findsOneWidget);

    // Sign-Up's own "Log In" link pops too, rather than stacking a second
    // Login on top of the first.
    await tester.tap(find.widgetWithText(TextButton, 'Sign Up'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Log In'));
    await tester.pumpAndSettle();
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.byType(SignUpScreen), findsNothing);
  });

  testWidgets('NFR-10: small screen at 2x text scale does not overflow', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onLogin: () async => throw const AuthNetworkException(),
    );
    // 320x568 dp — the smallest common Android phone class.
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(),
      api: api,
      physicalSize: const Size(640, 1136),
      textScale: 2.0,
    );
    tester.view.devicePixelRatio = 2.0;
    await tester.pump();

    await tester.enterText(_emailField, _email);
    await tester.enterText(_passwordField, _password);
    await tester.ensureVisible(buttonLabelled(_logIn));
    await tester.pumpAndSettle();
    await tester.tap(buttonLabelled(_logIn));
    await tester.pumpAndSettle();

    expect(find.text(AuthMessages.network), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('NFR-10: a 1:00:00 lock at 320 dp, 2x text does not overflow', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onLogin: () async =>
          throw const InvalidCredentialsException(retryAfterSeconds: 3600),
    );
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(),
      api: api,
      physicalSize: const Size(640, 1136),
      textScale: 2.0,
    );
    tester.view.devicePixelRatio = 2.0;
    await tester.pump();

    await tester.enterText(_emailField, _email);
    await tester.enterText(_passwordField, _password);
    await tester.ensureVisible(buttonLabelled(_logIn));
    await tester.pumpAndSettle();
    await tester.tap(buttonLabelled(_logIn));
    await tester.pump();
    await tester.pump();

    expect(find.text('Try again in 1:00:00'), findsOneWidget);
    expect(find.text(AuthMessages.incorrectCredentials), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
