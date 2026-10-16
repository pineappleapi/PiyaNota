import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/auth_session.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/state/auth_providers.dart';

/// [AuthApi] whose responses each test scripts directly, with call counts
/// so double-submission (PIYA-202 AC6 / PIYA-203 AC7) is observable.
class ScriptedAuthApi implements AuthApi {
  ScriptedAuthApi({
    this.onLogin,
    this.onSignUp,
    this.onRequestReset,
    this.onConfirmReset,
    this.onChangePassword,
  });

  Future<AuthSession> Function()? onLogin;
  Future<AuthSession> Function()? onSignUp;
  Future<void> Function()? onRequestReset;
  Future<void> Function()? onConfirmReset;
  Future<void> Function()? onChangePassword;
  int changePasswordCalls = 0;
  String? lastToken;
  String? lastCurrentPassword;
  int loginCalls = 0;
  int signUpCalls = 0;
  int requestResetCalls = 0;
  int confirmResetCalls = 0;
  String? lastEmail;
  String? lastResetToken;
  String? lastNewPassword;

  @override
  Future<void> requestPasswordReset({required String email}) {
    requestResetCalls++;
    lastEmail = email;
    return onRequestReset!();
  }

  @override
  Future<void> confirmPasswordReset({
    required String resetToken,
    required String newPassword,
    required String newPasswordConfirmation,
  }) {
    confirmResetCalls++;
    lastResetToken = resetToken;
    lastNewPassword = newPassword;
    return onConfirmReset!();
  }

  @override
  Future<void> changePassword({
    required String token,
    required String currentPassword,
    required String newPassword,
  }) {
    changePasswordCalls++;
    lastToken = token;
    lastCurrentPassword = currentPassword;
    lastNewPassword = newPassword;
    return onChangePassword!();
  }

  @override
  Future<AuthSession> login({required String email, required String password}) {
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

/// In-memory secure storage whose individual operations can be made to throw
/// [PlatformException] — what flutter_secure_storage raises when the Keystore
/// is unavailable or ciphertext can't be decrypted.
class FaultySecureStorage extends FlutterSecureStorage {
  FaultySecureStorage([Map<String, String>? initial]) : values = {...?initial};

  final Map<String, String> values;
  final Set<String> failWritesFor = {};
  final Set<String> failReadsFor = {};
  final Set<String> failDeletesFor = {};

  static PlatformException _failure(String op, String key) =>
      PlatformException(code: 'test-$op-failed', message: key);

  @override
  Future<void> write({
    required String key,
    required String? value,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (failWritesFor.contains(key)) throw _failure('write', key);
    if (value == null) {
      values.remove(key);
    } else {
      values[key] = value;
    }
  }

  @override
  Future<String?> read({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (failReadsFor.contains(key)) throw _failure('read', key);
    return values[key];
  }

  @override
  Future<void> delete({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (failDeletesFor.contains(key)) throw _failure('delete', key);
    values.remove(key);
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
  SessionStorage? storage,
  Map<String, WidgetBuilder> extraRoutes = const {},
  List<Override> extraOverrides = const [],
}) async {
  // A phone-sized viewport (the test default is 800x600 landscape), so
  // layout/overflow behaviour matches a real device.
  tester.view.physicalSize = physicalSize;
  tester.view.devicePixelRatio = 2.75;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        authApiProvider.overrideWithValue(api),
        if (storage != null) sessionStorageProvider.overrideWithValue(storage),
        ...extraOverrides,
      ],
      child: MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: TextScaler.linear(textScale)),
          child: child!,
        ),
        home: screen,
        routes: {
          AppRoutes.scoreLibrary: (_) =>
              const Scaffold(body: Text(libraryMarker)),
          AppRoutes.passwordReset: (_) =>
              const Scaffold(body: Text(passwordResetMarker)),
          if (stubLogin)
            AppRoutes.login: (_) => const Scaffold(body: Text(loginMarker)),
          if (stubSignUp)
            AppRoutes.signUp: (_) => const Scaffold(body: Text(signUpMarker)),
          ...extraRoutes,
        },
      ),
    ),
  );
}

Finder buttonLabelled(String label) =>
    find.ancestor(of: find.text(label), matching: find.byType(ElevatedButton));

bool isButtonEnabled(WidgetTester tester, String label) =>
    tester.widget<ElevatedButton>(buttonLabelled(label)).onPressed != null;
