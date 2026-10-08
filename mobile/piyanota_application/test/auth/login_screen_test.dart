import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/auth_session.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/auth/auth_messages.dart';
import 'package:piyanota_application/screens/auth/login_screen.dart';
import 'package:piyanota_application/screens/auth/sign_up_screen.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/session_storage.dart';

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
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

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
}
