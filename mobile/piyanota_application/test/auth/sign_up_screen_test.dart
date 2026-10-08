import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/auth_session.dart';
import 'package:piyanota_application/screens/auth/auth_messages.dart';
import 'package:piyanota_application/screens/auth/sign_up_screen.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/session_storage.dart';

import 'auth_test_harness.dart';

const _createAccount = 'Create Account';
const _validEmail = 'maria@example.com';
const _validPassword = 'choir2026';

Finder get _emailField => find.byType(TextFormField).at(0);
Finder get _passwordField => find.byType(TextFormField).at(1);
Finder get _confirmField => find.byType(TextFormField).at(2);

Future<void> _fill(
  WidgetTester tester, {
  String email = _validEmail,
  String password = _validPassword,
  String? confirm,
}) async {
  await tester.enterText(_emailField, email);
  await tester.enterText(_passwordField, password);
  await tester.enterText(_confirmField, confirm ?? password);
  await tester.pump();
}

Future<void> _tapCreate(WidgetTester tester) async {
  await tester.tap(buttonLabelled(_createAccount));
  await tester.pump();
}

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  testWidgets('AC1: Create Account disabled until all three fields filled', (
    tester,
  ) async {
    await pumpAuthScreen(
      tester,
      screen: const SignUpScreen(),
      api: ScriptedAuthApi(),
    );

    expect(isButtonEnabled(tester, _createAccount), isFalse);
    await tester.enterText(_emailField, _validEmail);
    await tester.enterText(_passwordField, _validPassword);
    await tester.pump();
    expect(isButtonEnabled(tester, _createAccount), isFalse);
    await tester.enterText(_confirmField, _validPassword);
    await tester.pump();
    expect(isButtonEnabled(tester, _createAccount), isTrue);
  });

  testWidgets('AC2: invalid email format flagged without submitting', (
    tester,
  ) async {
    final api = ScriptedAuthApi(onSignUp: () async => testSession());
    await pumpAuthScreen(tester, screen: const SignUpScreen(), api: api);

    await _fill(tester, email: 'maria@example');
    await _tapCreate(tester);

    expect(find.text(AuthMessages.emailInvalid), findsOneWidget);
    expect(api.signUpCalls, 0);
  });

  testWidgets('AC3: mismatched confirmation flagged without submitting', (
    tester,
  ) async {
    final api = ScriptedAuthApi(onSignUp: () async => testSession());
    await pumpAuthScreen(tester, screen: const SignUpScreen(), api: api);

    await _fill(tester, confirm: 'choir2027');
    await _tapCreate(tester);

    expect(find.text(AuthMessages.passwordsDoNotMatch), findsOneWidget);
    expect(api.signUpCalls, 0);
  });

  testWidgets('AC4: weak password flagged without submitting', (tester) async {
    final api = ScriptedAuthApi(onSignUp: () async => testSession());
    await pumpAuthScreen(tester, screen: const SignUpScreen(), api: api);

    // Long enough but no digit — fails PIYA-301 AC3's letter+number rule.
    await _fill(tester, password: 'choirsing');
    await _tapCreate(tester);

    expect(find.text(AuthMessages.passwordTooWeak), findsOneWidget);
    expect(api.signUpCalls, 0);
  });

  testWidgets('AC4: server-side strength rejection is surfaced', (
    tester,
  ) async {
    const serverMessage = 'Password too common.';
    final api = ScriptedAuthApi(
      onSignUp: () async => throw const AuthValidationException(serverMessage),
    );
    await pumpAuthScreen(tester, screen: const SignUpScreen(), api: api);

    await _fill(tester);
    await _tapCreate(tester);
    await tester.pumpAndSettle();

    expect(find.text(serverMessage), findsOneWidget);
  });

  testWidgets('AC5: already-registered email shows error with Login link', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onSignUp: () async => throw const EmailAlreadyRegisteredException(),
    );
    await pumpAuthScreen(
      tester,
      screen: const SignUpScreen(),
      api: api,
      stubLogin: true,
    );

    await _fill(tester);
    await _tapCreate(tester);
    await tester.pumpAndSettle();

    expect(find.text(AuthMessages.emailAlreadyRegistered), findsOneWidget);
    await tester.tap(find.text('Log in instead'));
    await tester.pumpAndSettle();
    expect(find.text(loginMarker), findsOneWidget);
  });

  testWidgets('AC6: success stores token and lands in library, no Login step', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onSignUp: () async => testSession(),
      onLogin: () async => fail('Sign-Up must not call Login'),
    );
    await pumpAuthScreen(tester, screen: const SignUpScreen(), api: api);

    await _fill(tester);
    await _tapCreate(tester);
    await tester.pumpAndSettle();

    expect(api.signUpCalls, 1);
    expect(api.loginCalls, 0);
    expect(
      await const FlutterSecureStorage().read(key: 'session_token'),
      'sess_a1b2c3d4',
    );
    expect(find.text(libraryMarker), findsOneWidget);
  });

  testWidgets('AC7: loading state shown and repeat submission blocked', (
    tester,
  ) async {
    final pending = Completer<AuthSession>();
    final api = ScriptedAuthApi(onSignUp: () => pending.future);
    await pumpAuthScreen(tester, screen: const SignUpScreen(), api: api);

    await _fill(tester);
    await _tapCreate(tester);

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await tester.tap(find.byType(ElevatedButton));
    await tester.pump();
    expect(api.signUpCalls, 1);

    pending.complete(testSession());
    await tester.pumpAndSettle();
    expect(find.text(libraryMarker), findsOneWidget);
  });

  testWidgets('"Already have an account? Log In" routes to Login', (
    tester,
  ) async {
    await pumpAuthScreen(
      tester,
      screen: const SignUpScreen(),
      api: ScriptedAuthApi(),
      stubLogin: true,
    );

    await tester.tap(find.widgetWithText(TextButton, 'Log In'));
    await tester.pumpAndSettle();

    expect(find.text(loginMarker), findsOneWidget);
  });

  testWidgets('unexpected error releases loading state', (tester) async {
    final api = ScriptedAuthApi(
      onSignUp: () async => throw StateError('misconfigured'),
    );
    await pumpAuthScreen(tester, screen: const SignUpScreen(), api: api);

    await _fill(tester);
    await _tapCreate(tester);
    await tester.pumpAndSettle();

    expect(find.text(AuthMessages.serverError), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(isButtonEnabled(tester, _createAccount), isTrue);
  });

  testWidgets('NFR-10: small screen at 2x text scale does not overflow', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onSignUp: () async => throw const EmailAlreadyRegisteredException(),
    );
    // 320x568 dp — the smallest common Android phone class.
    await pumpAuthScreen(
      tester,
      screen: const SignUpScreen(),
      api: api,
      physicalSize: const Size(640, 1136),
      textScale: 2.0,
    );
    tester.view.devicePixelRatio = 2.0;
    await tester.pump();

    // Weak + mismatched password: every field shows an error at once, then
    // the server banner — the tallest state the form can reach.
    await _fill(
      tester,
      email: 'maria@example',
      password: 'short',
      confirm: 'other',
    );
    await tester.ensureVisible(buttonLabelled(_createAccount));
    await tester.pumpAndSettle();
    await _tapCreate(tester);
    await tester.pumpAndSettle();
    expect(find.text(AuthMessages.emailInvalid), findsOneWidget);
    expect(find.text(AuthMessages.passwordTooWeak), findsOneWidget);
    expect(find.text(AuthMessages.passwordsDoNotMatch), findsOneWidget);
    expect(tester.takeException(), isNull);

    await _fill(tester);
    await tester.ensureVisible(buttonLabelled(_createAccount));
    await tester.pumpAndSettle();
    await _tapCreate(tester);
    await tester.pumpAndSettle();
    expect(find.text(AuthMessages.emailAlreadyRegistered), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('secure-storage failure blocks entry with a distinct error', (
    tester,
  ) async {
    final backing = FaultySecureStorage()..failWritesFor.add('session_token');
    await pumpAuthScreen(
      tester,
      screen: const SignUpScreen(),
      api: ScriptedAuthApi(onSignUp: () async => testSession()),
      storage: SessionStorage(backing),
    );

    await _fill(tester);
    await _tapCreate(tester);
    await tester.pumpAndSettle();

    expect(find.text(AuthMessages.sessionSaveFailed), findsOneWidget);
    expect(find.text(libraryMarker), findsNothing);
    expect(backing.values, isEmpty);
  });

  testWidgets('system back as root route (from onboarding) goes to Login', (
    tester,
  ) async {
    await pumpAuthScreen(
      tester,
      screen: const SignUpScreen(),
      api: ScriptedAuthApi(),
      stubLogin: true,
    );

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();

    expect(find.text(loginMarker), findsOneWidget);
  });
}
