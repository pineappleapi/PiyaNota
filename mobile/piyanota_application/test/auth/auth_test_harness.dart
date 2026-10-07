import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/auth_session.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/state/auth_providers.dart';

/// [AuthApi] whose responses each test scripts directly, with call counts
/// so double-submission (PIYA-202 AC6 / PIYA-203 AC7) is observable.
class ScriptedAuthApi implements AuthApi {
  ScriptedAuthApi({this.onLogin, this.onSignUp});

  Future<AuthSession> Function()? onLogin;
  Future<AuthSession> Function()? onSignUp;
  int loginCalls = 0;
  int signUpCalls = 0;
  String? lastEmail;

  @override
  Future<AuthSession> login({
    required String email,
    required String password,
  }) {
    loginCalls++;
    lastEmail = email;
    return onLogin!();
  }

  @override
  Future<AuthSession> signUp({
    required String email,
    required String password,
    required String passwordConfirmation,
  }) {
    signUpCalls++;
    lastEmail = email;
    return onSignUp!();
  }
}

AuthSession testSession() => AuthSession(
      userId: 214,
      email: 'maria@example.com',
      role: 'choir_member',
      sessionToken: 'sess_a1b2c3d4',
      expiresAt: DateTime.utc(2026, 11, 6),
    );

/// Route stubs are plain labelled pages so tests can assert *where* a tap
/// navigated without depending on those screens' implementations.
const libraryMarker = 'ROUTE:library';
const passwordResetMarker = 'ROUTE:password-reset';
const loginMarker = 'ROUTE:login';
const signUpMarker = 'ROUTE:sign-up';

Future<void> pumpAuthScreen(
  WidgetTester tester, {
  required Widget screen,
  required AuthApi api,
  bool stubLogin = false,
  bool stubSignUp = false,
  Size physicalSize = const Size(1080, 2340),
  double textScale = 1.0,
}) async {
  // A phone-sized viewport (the test default is 800x600 landscape), so
  // layout/overflow behaviour matches a real device.
  tester.view.physicalSize = physicalSize;
  tester.view.devicePixelRatio = 2.75;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [authApiProvider.overrideWithValue(api)],
      child: MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(
            textScaler: TextScaler.linear(textScale),
          ),
          child: child!,
        ),
        home: screen,
        routes: {
          AppRoutes.scoreLibrary: (_) => const Scaffold(body: Text(libraryMarker)),
          AppRoutes.passwordReset: (_) =>
              const Scaffold(body: Text(passwordResetMarker)),
          if (stubLogin)
            AppRoutes.login: (_) => const Scaffold(body: Text(loginMarker)),
          if (stubSignUp)
            AppRoutes.signUp: (_) => const Scaffold(body: Text(signUpMarker)),
        },
      ),
    ),
  );
}

Finder buttonLabelled(String label) =>
    find.ancestor(of: find.text(label), matching: find.byType(ElevatedButton));

bool isButtonEnabled(WidgetTester tester, String label) =>
    tester.widget<ElevatedButton>(buttonLabelled(label)).onPressed != null;
