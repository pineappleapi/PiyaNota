import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/auth/auth_messages.dart';
import 'package:piyanota_application/screens/auth/login_screen.dart';
import 'package:piyanota_application/screens/auth/password_reset_screen.dart';
import 'package:piyanota_application/screens/auth/widgets/auth_error_banner.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';

import 'auth_test_harness.dart';

const _sendCode = 'Send Code';
const _continue = 'Continue';
const _resetPassword = 'Reset Password';
const _email = 'maria@example.com';
const _code = '123456';
const _newPassword = 'choir2026';
const _demoCodePrefix = 'Your reset code is ';

Finder _field(int index) => find.byType(TextFormField).at(index);

/// Scrolls [label]'s button into view first, as a user would — with the
/// banner(s) and debug demo inbox above it, the CTA can sit below the fold.
Future<void> _tapButton(WidgetTester tester, String label) async {
  await tester.ensureVisible(buttonLabelled(label));
  await tester.pumpAndSettle();
  await tester.tap(buttonLabelled(label));
}

Future<void> _requestCode(WidgetTester tester, {String email = _email}) async {
  await tester.enterText(_field(0), email);
  await tester.pump();
  await _tapButton(tester, _sendCode);
  await tester.pumpAndSettle();
}

Future<void> _enterCode(WidgetTester tester, {String code = _code}) async {
  await tester.enterText(_field(0), code);
  await tester.pump();
  await _tapButton(tester, _continue);
  await tester.pumpAndSettle();
}

Future<void> _enterNewPassword(
  WidgetTester tester, {
  String password = _newPassword,
  String? confirm,
}) async {
  await tester.enterText(_field(0), password);
  await tester.enterText(_field(1), confirm ?? password);
  await tester.pump();
  await _tapButton(tester, _resetPassword);
  await tester.pump();
}

ScriptedAuthApi _happyApi() =>
    ScriptedAuthApi(onRequestReset: () async {}, onConfirmReset: () async {});

String _demoCode(WidgetTester tester) {
  final text = tester.widget<Text>(find.textContaining(_demoCodePrefix)).data!;
  return text.substring(_demoCodePrefix.length);
}

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    // The work owner (review H1) lives in SharedPreferences.
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets(
    'AC1: Send Code disabled until the email is non-empty and well-formed',
    (tester) async {
      final api = _happyApi();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: api,
      );

      expect(isButtonEnabled(tester, _sendCode), isFalse);
      for (final malformed in ['   ', 'maria', 'maria@', 'maria@example']) {
        await tester.enterText(_field(0), malformed);
        await tester.pump();
        expect(isButtonEnabled(tester, _sendCode), isFalse, reason: malformed);
      }

      // Keyboard "done" on a malformed email explains why, without a request.
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();
      expect(find.text(AuthMessages.emailInvalid), findsOneWidget);
      expect(api.requestResetCalls, 0);

      await tester.enterText(_field(0), _email);
      await tester.pump();
      expect(isButtonEnabled(tester, _sendCode), isTrue);
      expect(find.text(AuthMessages.emailInvalid), findsNothing);
    },
  );

  testWidgets('AC2: registered email shows the confirmation within 3 seconds', (
    tester,
  ) async {
    // Real fake latency (not zero), so the 3s budget is actually exercised.
    final api = FakeAuthApi();
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);

    await tester.enterText(_field(0), FakeAuthApi.demoEmail);
    await tester.pump();
    await tester.tap(buttonLabelled(_sendCode));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await tester.pump(const Duration(seconds: 3));
    expect(find.text(AuthMessages.resetCodeSent), findsOneWidget);
    expect(find.text('Enter Code'), findsOneWidget);
    // Debug demo inbox stands in for the email.
    expect(_demoCode(tester), matches(RegExp(r'^\d{6}$')));
  });

  testWidgets(
    'AC3: unregistered email shows the same confirmation and next step',
    (tester) async {
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: FakeAuthApi(latency: Duration.zero),
      );

      await _requestCode(tester, email: 'nobody@example.com');

      // Same message, same screen — nothing tells a stranger the email
      // isn't registered.
      expect(find.text(AuthMessages.resetCodeSent), findsOneWidget);
      expect(find.text('Enter Code'), findsOneWidget);
      expect(find.byType(AuthErrorBanner), findsNothing);
      expect(find.textContaining(_demoCodePrefix), findsNothing);
    },
  );

  testWidgets(
    'AC4: new password must meet the Sign-Up strength rule and match',
    (tester) async {
      final api = _happyApi();
      await pumpAuthScreen(
        tester,
        screen: const PasswordResetScreen(),
        api: api,
        stubLogin: true,
      );
      await _requestCode(tester);
      await _enterCode(tester);
      expect(find.text('New Password'), findsOneWidget);

      await _enterNewPassword(tester, password: 'short1', confirm: 'short1');
      expect(find.text(AuthMessages.passwordTooWeak), findsOneWidget);
      expect(api.confirmResetCalls, 0);

      await _enterNewPassword(tester, password: 'onlyletters');
      expect(find.text(AuthMessages.passwordTooWeak), findsOneWidget);
      expect(api.confirmResetCalls, 0);

      await _enterNewPassword(tester, confirm: 'choir2027');
      expect(find.text(AuthMessages.passwordTooWeak), findsNothing);
      expect(find.text(AuthMessages.passwordsDoNotMatch), findsOneWidget);
      expect(api.confirmResetCalls, 0);

      await _enterNewPassword(tester);
      await tester.pumpAndSettle();
      expect(api.confirmResetCalls, 1);
      expect(api.lastResetToken, _code);
      expect(api.lastNewPassword, _newPassword);
      // Opened with nothing underneath (e.g. a deep link): replaces to Login.
      expect(find.text(loginMarker), findsOneWidget);
    },
  );

  testWidgets(
    'AC5: success returns to the existing Login with a confirmation, and '
    'the new password works',
    (tester) async {
      final api = FakeAuthApi(latency: Duration.zero);
      await pumpAuthScreen(
        tester,
        screen: const LoginScreen(),
        api: api,
        extraRoutes: {
          AppRoutes.passwordReset: (_) => const PasswordResetScreen(),
        },
      );

      await tester.tap(find.text('Forgot Password?'));
      await tester.pumpAndSettle();
      await _requestCode(tester, email: FakeAuthApi.demoEmail);
      await _enterCode(tester, code: _demoCode(tester));
      await _enterNewPassword(tester);
      await tester.pumpAndSettle();

      expect(find.byType(PasswordResetScreen), findsNothing);
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.text(AuthMessages.passwordResetSuccess), findsOneWidget);
      expect(
        find.widgetWithText(TextFormField, FakeAuthApi.demoEmail),
        findsOneWidget,
      );

      // The old password no longer works; the new one does.
      await tester.enterText(_field(1), FakeAuthApi.demoPassword);
      await tester.pump();
      await tester.tap(buttonLabelled('Log In'));
      await tester.pumpAndSettle();
      expect(find.text(AuthMessages.incorrectCredentials), findsOneWidget);
      expect(find.text(AuthMessages.passwordResetSuccess), findsNothing);

      await tester.enterText(_field(1), _newPassword);
      await tester.pump();
      await tester.tap(buttonLabelled('Log In'));
      await tester.pumpAndSettle();
      expect(find.text(libraryMarker), findsOneWidget);
    },
  );

  testWidgets('AC5: Login shows the confirmation when reached by route', (
    tester,
  ) async {
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(passwordReset: PasswordResetSucceeded(_email)),
      api: ScriptedAuthApi(),
    );

    expect(find.text(AuthMessages.passwordResetSuccess), findsOneWidget);
    expect(find.widgetWithText(TextFormField, _email), findsOneWidget);
  });

  testWidgets('expired or used code (410) returns to the code step', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onRequestReset: () async {},
      onConfirmReset: () async => throw const ResetCodeInvalidException(),
    );
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);
    await _requestCode(tester);
    await _enterCode(tester);
    await _enterNewPassword(tester);
    await tester.pumpAndSettle();

    expect(find.text('Enter Code'), findsOneWidget);
    expect(find.text(AuthMessages.resetCodeInvalid), findsOneWidget);
    expect(find.widgetWithText(TextFormField, _code), findsNothing);
    expect(isButtonEnabled(tester, _continue), isFalse);

    // Resend gets a fresh code and swaps the error for the confirmation.
    await tester.ensureVisible(find.widgetWithText(TextButton, 'Resend code'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Resend code'));
    await tester.pumpAndSettle();
    expect(api.requestResetCalls, 2);
    expect(api.lastEmail, _email);
    expect(find.text(AuthMessages.resetCodeInvalid), findsNothing);
    expect(find.text(AuthMessages.resetCodeSent), findsOneWidget);
  });

  testWidgets('Resend code is locked for 30 seconds after each send', (
    tester,
  ) async {
    final api = _happyApi();
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);
    await _requestCode(tester);

    Finder resend() => find.widgetWithText(TextButton, 'Resend code');
    TextButton lockedButton() => tester.widget<TextButton>(
      find.ancestor(
        of: find.textContaining('Resend code ('),
        matching: find.byType(TextButton),
      ),
    );

    expect(find.text('Resend code (30s)'), findsOneWidget);
    expect(lockedButton().onPressed, isNull);

    await tester.pump(const Duration(seconds: 29));
    expect(find.text('Resend code (1s)'), findsOneWidget);
    expect(lockedButton().onPressed, isNull);

    await tester.pump(const Duration(seconds: 1));
    expect(tester.widget<TextButton>(resend()).onPressed, isNotNull);

    await tester.ensureVisible(resend());
    await tester.pumpAndSettle();
    await tester.tap(resend());
    await tester.pump();
    expect(api.requestResetCalls, 2);
    expect(find.text('Resend code (30s)'), findsOneWidget);
  });

  testWidgets('server rejection of the new password keeps the user on it', (
    tester,
  ) async {
    const serverMessage = 'Password too common.';
    final api = ScriptedAuthApi(
      onRequestReset: () async {},
      onConfirmReset: () async =>
          throw const AuthValidationException(serverMessage),
    );
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);
    await _requestCode(tester);
    await _enterCode(tester);
    await _enterNewPassword(tester);
    await tester.pumpAndSettle();

    expect(find.text(serverMessage), findsOneWidget);
    expect(find.text('New Password'), findsOneWidget);
    expect(isButtonEnabled(tester, _resetPassword), isTrue);
  });

  testWidgets('server error on confirm shows the generic error, no hang', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onRequestReset: () async {},
      onConfirmReset: () async => throw const AuthServerException(),
    );
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);
    await _requestCode(tester);
    await _enterCode(tester);
    await _enterNewPassword(tester);
    await tester.pumpAndSettle();

    expect(find.text(AuthMessages.serverError), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('New Password'), findsOneWidget);
  });

  testWidgets('network failure is distinct and recoverable on both requests', (
    tester,
  ) async {
    var failRequest = true;
    final api = ScriptedAuthApi(
      onRequestReset: () async {
        if (failRequest) throw const AuthNetworkException();
      },
      onConfirmReset: () async => throw const AuthNetworkException(),
    );
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);

    await _requestCode(tester);
    expect(find.text(AuthMessages.network), findsOneWidget);
    expect(find.text(AuthMessages.resetCodeSent), findsNothing);
    expect(find.text(_sendCode), findsOneWidget); // still on step 1
    expect(isButtonEnabled(tester, _sendCode), isTrue);

    failRequest = false;
    await _tapButton(tester, _sendCode);
    await tester.pumpAndSettle();
    await _enterCode(tester);
    await _enterNewPassword(tester);
    await tester.pumpAndSettle();
    expect(find.text(AuthMessages.network), findsOneWidget);
    expect(find.text('New Password'), findsOneWidget);
    expect(isButtonEnabled(tester, _resetPassword), isTrue);
  });

  testWidgets('loading state shown and repeat submission blocked', (
    tester,
  ) async {
    final pendingRequest = Completer<void>();
    final pendingConfirm = Completer<void>();
    final api = ScriptedAuthApi(
      onRequestReset: () => pendingRequest.future,
      onConfirmReset: () => pendingConfirm.future,
    );
    await pumpAuthScreen(
      tester,
      screen: const PasswordResetScreen(),
      api: api,
      stubLogin: true,
    );

    await tester.enterText(_field(0), _email);
    await tester.pump();
    await tester.tap(buttonLabelled(_sendCode));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await tester.tap(find.byType(ElevatedButton));
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump();
    expect(api.requestResetCalls, 1);
    pendingRequest.complete();
    await tester.pumpAndSettle();

    await _enterCode(tester);
    await _enterNewPassword(tester);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await tester.tap(find.byType(ElevatedButton));
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump();
    expect(api.confirmResetCalls, 1);
    pendingConfirm.complete();
    await tester.pumpAndSettle();
  });

  testWidgets('error banner clears once the user edits the field', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onRequestReset: () async => throw const AuthNetworkException(),
    );
    await pumpAuthScreen(tester, screen: const PasswordResetScreen(), api: api);

    await _requestCode(tester);
    expect(find.text(AuthMessages.network), findsOneWidget);
    await tester.enterText(_field(0), 'maria2@example.com');
    await tester.pump();
    expect(find.text(AuthMessages.network), findsNothing);
  });

  testWidgets('system back walks the steps back to Login, never exits', (
    tester,
  ) async {
    await pumpAuthScreen(
      tester,
      screen: const LoginScreen(),
      api: _happyApi(),
      extraRoutes: {
        AppRoutes.passwordReset: (_) => const PasswordResetScreen(),
      },
    );

    await tester.tap(find.text('Forgot Password?'));
    await tester.pumpAndSettle();
    await _requestCode(tester);
    await _enterCode(tester);
    expect(find.text('New Password'), findsOneWidget);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('Enter Code'), findsOneWidget);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.byType(TextFormField), findsOneWidget);
    expect(find.text(_sendCode), findsOneWidget);
    // The email the user typed survives stepping back.
    expect(find.widgetWithText(TextFormField, _email), findsOneWidget);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.byType(PasswordResetScreen), findsNothing);
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.text(AuthMessages.passwordResetSuccess), findsNothing);
  });

  testWidgets('NFR-10: every step fits a small screen at 2x text scale', (
    tester,
  ) async {
    final api = ScriptedAuthApi(
      onRequestReset: () async {},
      onConfirmReset: () async => throw const AuthNetworkException(),
    );
    // 320x568 dp — the smallest common Android phone class.
    await pumpAuthScreen(
      tester,
      screen: const PasswordResetScreen(),
      api: api,
      physicalSize: const Size(640, 1136),
      textScale: 2.0,
    );
    tester.view.devicePixelRatio = 2.0;
    await tester.pump();

    await tester.enterText(_field(0), _email);
    await tester.ensureVisible(buttonLabelled(_sendCode));
    await tester.pumpAndSettle();
    await tester.tap(buttonLabelled(_sendCode));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    await tester.enterText(_field(0), _code);
    await tester.ensureVisible(buttonLabelled(_continue));
    await tester.pumpAndSettle();
    await tester.tap(buttonLabelled(_continue));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    await _enterNewPassword(tester);
    await tester.pumpAndSettle();
    expect(find.text(AuthMessages.network), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
